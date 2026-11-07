from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_DIR = PROJECT_ROOT / "sample_project"


def make_settings(data_dir: Path, **overrides) -> Settings:
    values = dict(
        data_dir=data_dir, max_upload_mb=500, max_repository_mb=100, max_python_files=500, max_file_kb=1024,
        clone_timeout_seconds=60, openai_api_key="", openai_model="gpt-4o-mini",
        openai_embedding_model="text-embedding-3-small", openai_timeout_seconds=10, retrieval_mode="lexical",
        jira_base_url="", jira_email="", jira_api_token="", jira_allow_any_host=False, mcp_allowed_roots=(),
    )
    values.update(overrides)
    return Settings(**values)


def build_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path / "data")


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLE_DIR
