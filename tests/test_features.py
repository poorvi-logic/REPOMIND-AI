from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.errors import InputError
from app.index import RepositoryIndex
from app.ingestion import IngestionLimits
from app.llm import LLMClient
from app.main import create_app
from app.pipeline import analyze_directory
from tests.conftest import SAMPLE_DIR, make_settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path / "data")))


def _upload_sample(client: TestClient) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for path in sorted(SAMPLE_DIR.rglob("*.py")):
            bundle.write(path, arcname=path.relative_to(SAMPLE_DIR).as_posix())
    buffer.seek(0)
    response = client.post("/api/analyses/upload", files={"file": ("sample.zip", buffer, "application/zip")})
    assert response.status_code == 201, response.text
    return response.json()["analysis_id"]


def test_default_upload_limit_accepts_archives_larger_than_25_mb(client: TestClient, tmp_path: Path):
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("main.py", "def run():\n    return 1\n")
        bundle.writestr("assets/data.bin", os.urandom(30 * 1024 * 1024))
    with archive.open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": ("large.zip", handle, "application/zip")})
    assert response.status_code == 201, response.text
    assert response.json()["summary"]["python_files"] == 1
    assert client.get("/api/meta/config").json()["limits"]["max_upload_mb"] == 500


def test_bad_ai_key_is_rejected_with_a_plain_message(client: TestClient, monkeypatch):
    monkeypatch.setattr(LLMClient, "check_key", lambda self: "auth_error")
    response = client.post("/api/ai/connection", json={"api_key": "sk-test-invalid-key-value"})
    assert response.status_code == 400
    assert response.json()["detail"] == "OpenAI rejected this API key."
    assert client.get("/api/ai/status").json()["connected"] is False


def test_valid_ai_key_connects_without_echoing_the_key(client: TestClient, monkeypatch):
    monkeypatch.setattr(LLMClient, "check_key", lambda self: "ok")
    key = "sk-test-valid-key-1234567890"
    response = client.post("/api/ai/connection", json={"api_key": key})
    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["source"] == "session"
    assert key not in response.text
    assert client.delete("/api/ai/connection").json()["connected"] is False


def test_duplicate_jira_issue_is_blocked_before_contacting_jira(client: TestClient):
    analysis_id = _upload_sample(client)
    finding_id = client.get(f"/api/analyses/{analysis_id}/risks").json()["findings"][0]["id"]
    client.app.state.services.store.record_jira_ticket(
        analysis_id=analysis_id, finding_id=finding_id, project_key="OPS", issue_key="OPS-77",
        issue_url="https://example.atlassian.net/browse/OPS-77", summary="existing",
        created_at="2026-01-01T00:00:00+00:00",
    )
    response = client.post("/api/jira/tickets", json={
        "analysis_id": analysis_id, "finding_id": finding_id, "project_key": "OPS",
        "issue_type": "Task", "confirm": True,
    })
    assert response.status_code == 409
    assert "OPS-77" in response.json()["detail"]


def test_function_graph_can_be_limited_to_one_module(sample_dir: Path):
    analysis = analyze_directory(sample_dir, analysis_id="modulefilter01", repository_name="sample",
                                 source_type="local", source_ref="sample", limits=IngestionLimits())
    index = RepositoryIndex(analysis)
    graph = index.dependency_graph("functions", confidence="all", max_nodes=500, module="orders")
    assert graph["nodes"]
    assert any(node["module"] == "orders" for node in graph["nodes"])
    touching = {edge["source"] for edge in graph["edges"]} | {edge["target"] for edge in graph["edges"]}
    orders_ids = {symbol["id"] for symbol in analysis["symbols"] if symbol["file"] == "orders.py"}
    assert touching and all(item in touching for item in orders_ids if item in touching)
    assert all(edge["source"] in orders_ids or edge["target"] in orders_ids for edge in graph["edges"])
