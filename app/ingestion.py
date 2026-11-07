from __future__ import annotations

import os
import re
import shutil
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator

from git import Repo
from git.exc import GitCommandError, GitCommandNotFound

from .errors import ExternalServiceError, InputError, PayloadTooLargeError

SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules", "venv", "site-packages", "dist", "build", "__MACOSX"})
GITHUB_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]{1,100})"
)
_S_IFMT = 0o170000
_S_IFLNK = 0o120000
_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class IngestionLimits:
    max_python_files: int = 500
    max_file_bytes: int = 1024 * 1024
    max_repository_bytes: int = 100 * 1024 * 1024
    max_archive_entries: int = 50_000


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"


@dataclass(frozen=True)
class PythonSource:
    path: Path
    relative_path: str
    size_bytes: int


@dataclass
class ExtractionReport:
    extracted_files: int = 0
    warnings: list[str] = field(default_factory=list)
    other_file_types: dict[str, int] = field(default_factory=dict)


class _FileTooLarge(Exception):
    pass


def is_ignored_name(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIR_NAMES


def parse_github_url(raw_url: str) -> GitHubRepository:
    candidate = (raw_url or "").strip()
    if not candidate:
        raise InputError("Enter a GitHub repository URL.")
    if len(candidate) > 300:
        raise InputError("The GitHub URL is too long.")
    if candidate.startswith("github.com/"):
        candidate = "https://" + candidate
    candidate = candidate.rstrip("/")
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    match = GITHUB_URL_PATTERN.fullmatch(candidate)
    if not match:
        raise InputError(
            "Use the repository root URL, for example https://github.com/owner/repository. "
            "Only public HTTPS GitHub repositories are supported."
        )
    name = match.group("repo")
    if name in {".", ".."} or name.startswith("."):
        raise InputError("The repository name in the GitHub URL is not valid.")
    return GitHubRepository(owner=match.group("owner"), name=name)


def clone_repository(clone_url: str, destination: Path, timeout_seconds: int) -> str | None:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise InputError("Clone destination must be empty.")
    try:
        repo = Repo.clone_from(
            clone_url,
            destination,
            multi_options=["--depth=1", "--single-branch", "--no-tags"],
            env={"GIT_TERMINAL_PROMPT": "0"},
            kill_after_timeout=timeout_seconds,
        )
    except GitCommandNotFound as exc:
        raise ExternalServiceError("Git is not installed or is not available on PATH.") from exc
    except GitCommandError as exc:
        message = str(exc).lower()
        if "kill" in message or "timed out" in message or "timeout" in message:
            raise ExternalServiceError(f"Cloning timed out after {timeout_seconds} seconds.") from exc
        raise InputError("GitHub clone failed. Check that the repository exists and is publicly readable.") from exc
    commit = None
    try:
        commit = repo.head.commit.hexsha
    except (ValueError, TypeError):
        commit = None
    finally:
        repo.close()
    shutil.rmtree(destination / ".git", ignore_errors=True)
    return commit


def save_upload_stream(source: BinaryIO, destination: Path, max_bytes: int) -> int:
    written = 0
    with destination.open("wb") as sink:
        while chunk := source.read(_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise PayloadTooLargeError(f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            sink.write(chunk)
    if written == 0:
        raise InputError("The uploaded file is empty.")
    return written


def _resolve_member(destination: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise InputError("The ZIP archive contains an absolute path, which is not allowed.")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise InputError("The ZIP archive contains a path traversal entry, which is not allowed.")
    base = destination.resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise InputError("The ZIP archive contains a path outside the workspace, which is not allowed.")
    return target


def _write_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, max_bytes: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with archive.open(info) as source, target.open("wb") as sink:
            while chunk := source.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise _FileTooLarge()
                sink.write(chunk)
    except _FileTooLarge:
        target.unlink(missing_ok=True)
        return -1
    return written


def extract_python_archive(archive_path: Path, destination: Path, limits: IngestionLimits) -> ExtractionReport:
    if not zipfile.is_zipfile(archive_path):
        raise InputError("The uploaded file is not a valid ZIP archive.")
    report = ExtractionReport()
    destination.mkdir(parents=True, exist_ok=True)
    total_written = 0
    skipped_large = 0
    skipped_links = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > limits.max_archive_entries:
            raise PayloadTooLargeError("The ZIP archive contains too many entries.")
        for info in entries:
            target = _resolve_member(destination, info.filename)
            if info.is_dir():
                continue
            if ((info.external_attr >> 16) & _S_IFMT) == _S_IFLNK:
                skipped_links += 1
                continue
            parts = info.filename.replace("\\", "/").split("/")
            if any(is_ignored_name(part) for part in parts[:-1]):
                continue
            if not info.filename.lower().endswith(".py"):
                extension = Path(info.filename).suffix.lower() or "(no extension)"
                report.other_file_types[extension] = report.other_file_types.get(extension, 0) + 1
                continue
            if report.extracted_files >= limits.max_python_files:
                report.warnings.append(
                    f"Extraction stopped after {limits.max_python_files} Python files; the analysis is partial."
                )
                break
            written = _write_member(archive, info, target, limits.max_file_bytes)
            if written < 0:
                skipped_large += 1
                continue
            total_written += written
            if total_written > limits.max_repository_bytes:
                raise PayloadTooLargeError(
                    f"Repository source exceeds the {limits.max_repository_bytes // (1024 * 1024)} MB limit."
                )
            report.extracted_files += 1
    if skipped_large:
        report.warnings.append(f"{skipped_large} Python file(s) were skipped because they exceed the file size limit.")
    if skipped_links:
        report.warnings.append(f"{skipped_links} symbolic link(s) were ignored for safety.")
    if report.extracted_files == 0:
        raise InputError("No Python files were found in the upload.")
    return report


def detect_repository_root(directory: Path) -> Path:
    current = directory
    for _ in range(8):
        entries = [entry for entry in current.iterdir() if not is_ignored_name(entry.name)]
        has_python_here = any(entry.is_file() and entry.suffix == ".py" for entry in entries)
        child_directories = [entry for entry in entries if entry.is_dir()]
        if has_python_here or len(child_directories) != 1:
            break
        child = child_directories[0]
        if (child / "__init__.py").exists():
            break
        current = child
    return current


def detect_source_roots(root: Path) -> tuple[str, ...]:
    candidate = root / "src"
    if not candidate.is_dir() or (candidate / "__init__.py").exists():
        return ()
    children = [child for child in candidate.iterdir() if not is_ignored_name(child.name)]
    has_package = any(child.is_dir() and (child / "__init__.py").exists() for child in children)
    has_module = any(child.is_file() and child.suffix == ".py" for child in children)
    return ("src",) if has_package or has_module else ()


def discover_python_files(root: Path, limits: IngestionLimits) -> tuple[list[PythonSource], list[str]]:
    root = root.resolve()
    sources: list[PythonSource] = []
    warnings: list[str] = []
    total_bytes = 0
    oversized = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(name for name in dirnames if not is_ignored_name(name) and not (current / name).is_symlink())
        for name in sorted(filenames):
            if not name.endswith(".py") or name.startswith("."):
                continue
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            if size > limits.max_file_bytes:
                oversized += 1
                continue
            if len(sources) >= limits.max_python_files:
                warnings.append(f"Analysis stopped after {limits.max_python_files} Python files; results are partial.")
                return sorted(sources, key=lambda item: item.relative_path), warnings
            total_bytes += size
            if total_bytes > limits.max_repository_bytes:
                raise PayloadTooLargeError("Repository source exceeds the configured size limit.")
            sources.append(PythonSource(path=path, relative_path=path.relative_to(root).as_posix(), size_bytes=size))
    if oversized:
        warnings.append(f"{oversized} Python file(s) were skipped because they exceed the file size limit.")
    return sorted(sources, key=lambda item: item.relative_path), warnings


@contextmanager
def analysis_workspace(base_dir: Path, analysis_id: str) -> Iterator[Path]:
    workspace = base_dir / analysis_id
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def remove_stale_workspaces(base_dir: Path) -> int:
    if not base_dir.exists():
        return 0
    removed = 0
    for entry in base_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def count_other_file_types(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not is_ignored_name(name)]
        for name in filenames:
            if name.endswith(".py") or name.startswith("."):
                continue
            extension = Path(name).suffix.lower() or "(no extension)"
            counts[extension] = counts.get(extension, 0) + 1
    return counts
