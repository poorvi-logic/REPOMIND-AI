from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.errors import ExternalServiceError, InputError, PayloadTooLargeError
from app.ingestion import (
    IngestionLimits, clone_repository, detect_repository_root, discover_python_files,
    extract_python_archive, parse_github_url, remove_stale_workspaces,
)
from tests.conftest import build_zip


@pytest.mark.parametrize("url, owner, name", [
    ("https://github.com/psf/requests", "psf", "requests"),
    ("https://github.com/psf/requests/", "psf", "requests"),
    ("https://github.com/psf/requests.git", "psf", "requests"),
    ("github.com/owner-name/my.repo_1", "owner-name", "my.repo_1"),
])
def test_github_urls_are_normalised(url, owner, name):
    repository = parse_github_url(url)
    assert (repository.owner, repository.name) == (owner, name)
    assert repository.clone_url == f"https://github.com/{owner}/{name}.git"


@pytest.mark.parametrize("url", [
    "", "   ", "http://github.com/psf/requests", "https://gitlab.com/psf/requests",
    "https://github.com/psf", "https://github.com/psf/requests/tree/main/src",
    "https://github.com/psf/requests?tab=readme", "https://github.com/../etc",
    "https://github.com/psf/..", "https://github.com/-bad/repo", "x" * 301,
    "https://evil.example.com/github.com/psf/requests",
])
def test_invalid_github_urls_are_rejected(url):
    with pytest.raises(InputError):
        parse_github_url(url)


def test_zip_extraction_keeps_python_files_only(tmp_path: Path):
    archive = build_zip(tmp_path / "repo.zip", {
        "project/app.py": "x = 1\n",
        "project/readme.md": "not python",
        "project/pkg/__init__.py": "",
        "project/.git/config.py": "hidden",
        "project/node_modules/lib.py": "ignored",
    })
    destination = tmp_path / "out"
    report = extract_python_archive(archive, destination, IngestionLimits())
    assert report.extracted_files == 2
    assert (destination / "project" / "app.py").exists()
    assert not (destination / "project" / "readme.md").exists()
    assert not (destination / "project" / "node_modules").exists()


@pytest.mark.parametrize("member", ["../escape.py", "/abs/escape.py", "C:/windows/escape.py", "a/../../escape.py"])
def test_zip_path_traversal_is_rejected(tmp_path: Path, member: str):
    archive = build_zip(tmp_path / "bad.zip", {member: "print('x')"})
    with pytest.raises(InputError):
        extract_python_archive(archive, tmp_path / "out", IngestionLimits())
    assert not (tmp_path / "escape.py").exists()


def test_non_zip_upload_is_rejected(tmp_path: Path):
    fake = tmp_path / "upload.zip"
    fake.write_text("this is not a zip", encoding="utf-8")
    with pytest.raises(InputError):
        extract_python_archive(fake, tmp_path / "out", IngestionLimits())


def test_zip_without_python_files_is_rejected(tmp_path: Path):
    archive = build_zip(tmp_path / "docs.zip", {"README.md": "hello"})
    with pytest.raises(InputError, match="No Python files"):
        extract_python_archive(archive, tmp_path / "out", IngestionLimits())


def test_oversized_python_file_is_skipped_with_warning(tmp_path: Path):
    archive = build_zip(tmp_path / "big.zip", {"small.py": "x = 1\n", "big.py": "y = 2\n" * 500})
    report = extract_python_archive(archive, tmp_path / "out", IngestionLimits(max_file_bytes=100))
    assert report.extracted_files == 1
    assert any("size limit" in warning for warning in report.warnings)


def test_repository_size_limit_is_enforced(tmp_path: Path):
    archive = build_zip(tmp_path / "many.zip", {f"m{i}.py": "x = 1\n" * 100 for i in range(10)})
    with pytest.raises(PayloadTooLargeError):
        extract_python_archive(archive, tmp_path / "out", IngestionLimits(max_repository_bytes=1000))


def test_python_file_count_limit_produces_partial_warning(tmp_path: Path):
    archive = build_zip(tmp_path / "count.zip", {f"m{i}.py": "x = 1\n" for i in range(5)})
    report = extract_python_archive(archive, tmp_path / "out", IngestionLimits(max_python_files=2))
    assert report.extracted_files == 2
    assert any("partial" in warning for warning in report.warnings)


def test_archive_entry_limit_is_enforced(tmp_path: Path):
    archive = build_zip(tmp_path / "entries.zip", {f"m{i}.py": "x" for i in range(4)})
    with pytest.raises(PayloadTooLargeError):
        extract_python_archive(archive, tmp_path / "out", IngestionLimits(max_archive_entries=2))


def test_root_detection_descends_into_single_wrapper_folder(tmp_path: Path):
    (tmp_path / "repo-main" / "pkg").mkdir(parents=True)
    (tmp_path / "repo-main" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    assert detect_repository_root(tmp_path) == tmp_path / "repo-main"


def test_root_detection_stops_at_package_directory(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    assert detect_repository_root(tmp_path) == tmp_path


def test_root_detection_keeps_top_level_python_files(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    assert detect_repository_root(tmp_path) == tmp_path


def test_discovery_skips_ignored_directories_but_not_repo_under_build_path(tmp_path: Path):
    repo = tmp_path / "build" / "dist-project"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "skip.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "skip.py").write_text("x = 1\n", encoding="utf-8")
    sources, _ = discover_python_files(repo, IngestionLimits())
    assert [item.relative_path for item in sources] == ["src/app.py"]


def test_discovery_ignores_symbolic_links(tmp_path: Path):
    real = tmp_path / "real.py"
    real.write_text("x = 1\n", encoding="utf-8")
    try:
        os.symlink(real, tmp_path / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this platform")
    sources, _ = discover_python_files(tmp_path, IngestionLimits())
    assert [item.relative_path for item in sources] == ["real.py"]


def test_clone_repository_from_local_git_fixture(tmp_path: Path):
    source = tmp_path / "upstream"
    source.mkdir()
    (source / "module.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=source, check=True)
    destination = tmp_path / "clone"
    commit = clone_repository(str(source), destination, timeout_seconds=60)
    assert commit and len(commit) == 40
    assert (destination / "module.py").exists()
    assert not (destination / ".git").exists()


def test_clone_failure_is_reported_without_exposing_stack(tmp_path: Path):
    with pytest.raises((InputError, ExternalServiceError)):
        clone_repository(str(tmp_path / "does-not-exist"), tmp_path / "clone", timeout_seconds=30)


def test_stale_workspaces_are_removed(tmp_path: Path):
    (tmp_path / "old1" / "source").mkdir(parents=True)
    (tmp_path / "old2").mkdir()
    assert remove_stale_workspaces(tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
