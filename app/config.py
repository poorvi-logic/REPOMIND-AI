from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MB = 1024 * 1024


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_mb: int
    max_repository_mb: int
    max_python_files: int
    max_file_kb: int
    clone_timeout_seconds: int
    openai_api_key: str
    openai_model: str
    openai_embedding_model: str
    openai_timeout_seconds: int
    retrieval_mode: str
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_allow_any_host: bool
    mcp_allowed_roots: tuple[Path, ...]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "repomind.db"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def frontend_dist_dir(self) -> Path:
        return BASE_DIR / "frontend" / "dist"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    data_dir = Path(_env_str("REPOMIND_DATA_DIR") or str(BASE_DIR / "data")).expanduser()
    retrieval_mode = (_env_str("RETRIEVAL_MODE") or "lexical").lower()
    if retrieval_mode not in {"lexical", "hybrid"}:
        raise ValueError("RETRIEVAL_MODE must be 'lexical' or 'hybrid'.")
    roots_raw = _env_str("REPOMIND_MCP_ALLOWED_ROOTS")
    allowed_roots = tuple(
        Path(item).expanduser().resolve() for item in roots_raw.split(os.pathsep) if item.strip()
    )
    return Settings(
        data_dir=data_dir,
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 500),
        max_repository_mb=_env_int("MAX_REPOSITORY_MB", 100),
        max_python_files=_env_int("MAX_PYTHON_FILES", 500),
        max_file_kb=_env_int("MAX_FILE_KB", 1024),
        clone_timeout_seconds=_env_int("CLONE_TIMEOUT_SECONDS", 120),
        openai_api_key=_env_str("OPENAI_API_KEY"),
        openai_model=_env_str("OPENAI_MODEL") or "gpt-4o-mini",
        openai_embedding_model=_env_str("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small",
        openai_timeout_seconds=_env_int("OPENAI_TIMEOUT_SECONDS", 45),
        retrieval_mode=retrieval_mode,
        jira_base_url=_env_str("JIRA_BASE_URL"),
        jira_email=_env_str("JIRA_EMAIL"),
        jira_api_token=_env_str("JIRA_API_TOKEN"),
        jira_allow_any_host=_env_bool("JIRA_ALLOW_ANY_HOST", False),
        mcp_allowed_roots=allowed_roots,
    )
