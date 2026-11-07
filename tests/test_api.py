from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.services as services_module
from app.jira import JiraClient, JiraCredentials
from app.main import create_app
from tests.conftest import SAMPLE_DIR, build_zip, make_settings
from tests.fakes import FakeLLM

JIRA_CREDENTIALS = {"site_url": "https://team.atlassian.net", "email": "dev@example.com", "api_token": "api-token-abcdef12"}


def _sample_zip(tmp_path: Path) -> Path:
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(SAMPLE_DIR.rglob("*.py")):
            bundle.write(path, arcname=f"sample_project/{path.relative_to(SAMPLE_DIR).as_posix()}")
    return archive


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path / "data")))


@pytest.fixture
def analysis_id(client: TestClient, tmp_path: Path) -> str:
    with _sample_zip(tmp_path).open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": ("sample.zip", handle, "application/zip")})
    assert response.status_code == 201, response.text
    return response.json()["analysis_id"]


def test_health_and_runtime_config_never_expose_secrets(client: TestClient):
    assert client.get("/api/health").json() == {"status": "ok", "project": "RepoMind AI"}
    config = client.get("/api/meta/config").json()
    assert config["ai_enabled"] is False
    assert "api_token" not in json.dumps(config)
    assert config["jira"]["configured"] is False


def test_zip_upload_creates_a_persisted_analysis(client: TestClient, tmp_path: Path):
    with _sample_zip(tmp_path).open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": ("sample.zip", handle, "application/zip")})
    assert response.status_code == 201
    body = response.json()
    assert body["repository"] == "sample"
    assert body["summary"]["python_files"] == 11
    assert client.get(f"/api/analyses/{body['analysis_id']}").status_code == 200
    assert client.get("/api/analyses").json()[0]["analysis_id"] == body["analysis_id"]


def test_non_zip_and_empty_uploads_are_rejected(client: TestClient):
    response = client.post("/api/analyses/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert "zip" in response.json()["detail"].lower()
    empty = client.post("/api/analyses/upload", files={"file": ("empty.zip", b"", "application/zip")})
    assert empty.status_code == 400


def test_zip_without_python_files_is_rejected(client: TestClient, tmp_path: Path):
    archive = build_zip(tmp_path / "docs.zip", {"README.md": "hi"})
    with archive.open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": ("docs.zip", handle, "application/zip")})
    assert response.status_code == 400
    assert "Python" in response.json()["detail"]


def test_path_traversal_archive_is_rejected_over_http(client: TestClient, tmp_path: Path):
    archive = build_zip(tmp_path / "evil.zip", {"../escape.py": "x = 1"})
    with archive.open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": ("evil.zip", handle, "application/zip")})
    assert response.status_code == 400
    assert "path" in response.json()["detail"].lower()


def test_upload_size_limit_returns_413(tmp_path: Path):
    settings = make_settings(tmp_path / "data", max_upload_mb=1)
    small_client = TestClient(create_app(settings))
    payload = io.BytesIO(b"0" * (1024 * 1024 + 10))
    response = small_client.post("/api/analyses/upload", files={"file": ("big.zip", payload, "application/zip")})
    assert response.status_code == 413


def test_github_url_validation_happens_before_cloning(client: TestClient):
    response = client.post("/api/analyses/github", json={"url": "https://gitlab.com/a/b"})
    assert response.status_code == 400
    assert "GitHub" in response.json()["detail"] or "repository" in response.json()["detail"]
    empty = client.post("/api/analyses/github", json={"url": ""})
    assert empty.status_code == 400 or empty.status_code == 422


def test_file_tree_detail_and_source_endpoints(client: TestClient, analysis_id: str):
    files = client.get(f"/api/analyses/{analysis_id}/files").json()
    assert {item["path"] for item in files} >= {"main.py", "orders.py", "payment.py"}
    detail = client.get(f"/api/analyses/{analysis_id}/file", params={"path": "orders.py"}).json()
    assert {c["name"] for c in detail["classes"]} == {"Order", "OrderService"}
    source = client.get(f"/api/analyses/{analysis_id}/source", params={"path": "payment.py"}).json()
    assert "def validate_payment" in source["content"]
    missing = client.get(f"/api/analyses/{analysis_id}/file", params={"path": "missing.py"})
    assert missing.status_code == 404


def test_symbol_search_and_detail_endpoints(client: TestClient, analysis_id: str):
    results = client.get(f"/api/analyses/{analysis_id}/symbols", params={"q": "refund"}).json()
    assert any(item["qualname"] == "OrderService.refund" for item in results)
    detail = client.get(f"/api/analyses/{analysis_id}/symbols/main.py::checkout").json()
    assert detail["callees"][0]["confidence"] == "confirmed"
    assert client.get(f"/api/analyses/{analysis_id}/symbols/nope.py::missing").status_code == 404


def test_dependency_endpoints_return_graph_and_summary(client: TestClient, analysis_id: str):
    graph = client.get(f"/api/analyses/{analysis_id}/dependencies").json()
    assert graph["scope"] == "modules" and graph["nodes"] and graph["edges"]
    functions = client.get(f"/api/analyses/{analysis_id}/dependencies",
                           params={"scope": "functions", "confidence": "all", "max_nodes": 25}).json()
    assert len(functions["nodes"]) <= 25
    summary = client.get(f"/api/analyses/{analysis_id}/dependencies/summary").json()
    assert summary["summary"]["circular_dependencies"] == 1
    module = client.get(f"/api/analyses/{analysis_id}/modules/orders/dependencies").json()
    assert "notifications" in {item["module"] for item in module["imports"]}
    assert client.get(f"/api/analyses/{analysis_id}/modules/ghost/dependencies").status_code == 404


def test_invalid_query_parameters_are_rejected(client: TestClient, analysis_id: str):
    response = client.get(f"/api/analyses/{analysis_id}/dependencies", params={"scope": "galaxy"})
    assert response.status_code == 422
    response = client.get(f"/api/analyses/{analysis_id}/dependencies", params={"max_nodes": 2})
    assert response.status_code == 422


def test_risk_endpoints_filter_and_return_context(client: TestClient, analysis_id: str):
    risks = client.get(f"/api/analyses/{analysis_id}/risks", params={"min_severity": "high"}).json()
    assert risks["total"] >= 3
    finding_id = risks["findings"][0]["id"]
    single = client.get(f"/api/analyses/{analysis_id}/risks/{finding_id}").json()
    assert single["context"] and single["rule_id"] == risks["findings"][0]["rule_id"]
    assert client.get(f"/api/analyses/{analysis_id}/risks/RM-NOPE-000").status_code == 404


def test_search_and_ask_are_grounded_without_an_api_key(client: TestClient, analysis_id: str):
    search = client.get(f"/api/analyses/{analysis_id}/search", params={"q": "payment validation"}).json()
    assert search["results"][0]["file"] == "payment.py"
    answer = client.post(f"/api/analyses/{analysis_id}/ask", json={"question": "Where is payment validation?"}).json()
    assert answer["mode"] == "deterministic"
    assert answer["references"]
    declined = client.post(f"/api/analyses/{analysis_id}/ask", json={"question": "zebra quantum banana"}).json()
    assert declined["insufficient_evidence"] is True
    empty = client.post(f"/api/analyses/{analysis_id}/ask", json={"question": ""})
    assert empty.status_code == 422


def test_explanations_fall_back_deterministically(client: TestClient, analysis_id: str):
    file_result = client.post(f"/api/analyses/{analysis_id}/explain/file", json={"path": "payment.py"}).json()
    assert file_result["mode"] == "deterministic" and file_result["ai_status"] == "disabled"
    symbol = client.post(f"/api/analyses/{analysis_id}/explain/symbol", json={"symbol_id": "main.py::checkout"}).json()
    assert "checkout" in symbol["text"]
    architecture = client.post(f"/api/analyses/{analysis_id}/explain/architecture").json()
    assert "Project sample" in architecture["text"]
    module = client.post(f"/api/analyses/{analysis_id}/explain/module", json={"module": "orders"}).json()
    assert "orders" in module["text"]
    flow = client.post(f"/api/analyses/{analysis_id}/explain/flow", json={"symbol_id": "main.py::main", "depth": 2}).json()
    assert "checkout" in flow["text"]


def test_explanations_use_the_llm_when_available(tmp_path: Path, analysis_id_factory=None):
    settings = make_settings(tmp_path / "data")
    app = create_app(settings)
    app.state.services.llm = FakeLLM(reply="Explained by the fake model.")
    client = TestClient(app)
    with _sample_zip(tmp_path).open("rb") as handle:
        analysis = client.post("/api/analyses/upload", files={"file": ("s.zip", handle, "application/zip")}).json()
    result = client.post(f"/api/analyses/{analysis['analysis_id']}/explain/file", json={"path": "payment.py"}).json()
    assert result["mode"] == "llm" and result["text"] == "Explained by the fake model."
    answer = client.post(f"/api/analyses/{analysis['analysis_id']}/ask",
                         json={"question": "Where is payment validation?"}).json()
    assert answer["mode"] == "llm"


def test_hybrid_retrieval_uses_embeddings_when_configured(tmp_path: Path):
    settings = make_settings(tmp_path / "data", retrieval_mode="hybrid")
    app = create_app(settings)
    fake = FakeLLM()
    app.state.services.llm = fake
    client = TestClient(app)
    with _sample_zip(tmp_path).open("rb") as handle:
        analysis = client.post("/api/analyses/upload", files={"file": ("s.zip", handle, "application/zip")}).json()
    search = client.get(f"/api/analyses/{analysis['analysis_id']}/search", params={"q": "payment validation"}).json()
    assert search["method"] == "hybrid"
    assert fake.embed_calls >= 1
    stored = app.state.services.store.load_embeddings(analysis["analysis_id"], fake.embedding_model)
    assert stored is not None and len(stored[0]) > 0


def test_report_is_generated_stored_and_downloadable(client: TestClient, analysis_id: str):
    created = client.post(f"/api/analyses/{analysis_id}/report").json()
    assert created["download_url"].endswith("/report/download")
    download = client.get(created["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    report = download.json()
    assert report["analysis"]["analysis_id"] == analysis_id
    assert report["disclaimer"]
    assert "source" not in json.dumps(report["files"][0]).lower() or "content" not in report["files"][0]


def test_legacy_endpoints_keep_working_against_the_latest_analysis(client: TestClient, tmp_path: Path):
    with _sample_zip(tmp_path).open("rb") as handle:
        client.post("/api/analyze/upload", files={"file": ("sample.zip", handle, "application/zip")})
    latest = client.get("/api/report/latest").json()
    assert latest["summary"]["python_files"] == 11
    assert latest["findings"]
    assert client.get("/api/search", params={"q": "payment validation"}).json()["results"]
    assert client.post("/api/ask", json={"question": "Where is payment validation?"}).json()["evidence"]
    assert "explanation" in client.get("/api/explain/payment.py").json()
    draft = client.post("/api/ticket-draft", json={"finding_index": 0}).json()
    assert draft["summary"].startswith("[RepoMind]")
    assert client.get("/api/report/download").status_code == 200


def test_legacy_endpoints_report_missing_analysis(client: TestClient):
    response = client.get("/api/report/latest")
    assert response.status_code == 404
    assert "No repository" in response.json()["detail"]


def test_delete_removes_the_analysis_and_its_report(client: TestClient, analysis_id: str):
    client.post(f"/api/analyses/{analysis_id}/report")
    assert client.delete(f"/api/analyses/{analysis_id}").status_code == 200
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 404


def test_unknown_or_malformed_analysis_ids(client: TestClient):
    assert client.get("/api/analyses/aaaaaaaaaaaa/files").status_code == 404
    assert client.get("/api/analyses/not-valid/files").status_code == 422


def test_settings_validate_and_persist_preferences(client: TestClient):
    assert client.get("/api/settings").json()["graph_max_nodes"] == 150
    updated = client.put("/api/settings", json={"graph_max_nodes": 220, "default_risk_severity": "medium"}).json()
    assert updated["graph_max_nodes"] == 220 and updated["default_risk_severity"] == "medium"
    assert client.get("/api/settings").json()["graph_max_nodes"] == 220
    assert client.put("/api/settings", json={"graph_max_nodes": 5}).status_code == 422
    assert client.put("/api/settings", json={"api_key": "should-not-store"}).status_code == 422


def test_mcp_catalog_and_client_configuration(client: TestClient):
    tools = client.get("/api/mcp/tools").json()
    assert len(tools) == 8
    config = client.get("/api/mcp/config").json()
    assert config["mcpServers"]["repomind-ai"]["args"] == ["-m", "app.mcp_server"]


def test_jira_status_and_guarded_creation_without_credentials(client: TestClient, analysis_id: str):
    status = client.get("/api/jira/status").json()
    assert status["configured"] is False
    findings = client.get(f"/api/analyses/{analysis_id}/risks").json()["findings"]
    preview = client.post("/api/jira/tickets/preview", json={
        "analysis_id": analysis_id, "finding_id": findings[0]["id"], "project_key": "OPS", "issue_type": "Task",
    })
    assert preview.status_code == 200
    assert preview.json()["description_adf"]["type"] == "doc"
    refused = client.post("/api/jira/tickets", json={
        "analysis_id": analysis_id, "finding_id": findings[0]["id"], "project_key": "OPS", "issue_type": "Task",
        "confirm": False,
    })
    assert refused.status_code == 400
    unconfigured = client.post("/api/jira/tickets", json={
        "analysis_id": analysis_id, "finding_id": findings[0]["id"], "project_key": "OPS", "issue_type": "Task",
        "confirm": True,
    })
    assert unconfigured.status_code == 409


def test_jira_connect_create_status_and_history_with_mocked_jira(client: TestClient, analysis_id: str, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/myself":
            return httpx.Response(200, json={"accountId": "a1", "displayName": "Dev", "active": True})
        if path == "/rest/api/3/issue" and request.method == "POST":
            body = json.loads(request.content)
            assert body["fields"]["description"]["type"] == "doc"
            return httpx.Response(201, json={"id": "9", "key": "OPS-7"})
        if path == "/rest/api/3/issue/OPS-7":
            return httpx.Response(200, json={"key": "OPS-7", "fields": {
                "summary": "x", "status": {"name": "To Do"}, "priority": None, "assignee": None, "updated": None}})
        if path == "/rest/api/3/project/search":
            return httpx.Response(200, json={"values": [{"key": "OPS", "name": "Ops", "id": "1"}]})
        if path == "/rest/api/3/project/OPS":
            return httpx.Response(200, json={"issueTypes": [{"name": "Task"}]})
        return httpx.Response(404, json={})

    def transport_client(credentials):
        return JiraClient(credentials, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(services_module, "JiraClient", transport_client)
    services = client.app.state.services
    services.jira_client = lambda: JiraClient(services.jira.current()[0], transport=httpx.MockTransport(handler))

    connected = client.post("/api/jira/connection", json=JIRA_CREDENTIALS)
    assert connected.status_code == 200
    assert connected.json()["identity"]["display_name"] == "Dev"
    assert "api-token" not in connected.text

    projects = client.get("/api/jira/projects").json()
    assert projects[0]["issue_types"] == ["Task"]

    findings = client.get(f"/api/analyses/{analysis_id}/risks").json()["findings"]
    created = client.post("/api/jira/tickets", json={
        "analysis_id": analysis_id, "finding_id": findings[0]["id"], "project_key": "OPS",
        "issue_type": "Task", "confirm": True,
    })
    assert created.status_code == 201
    assert created.json()["issue_key"] == "OPS-7"
    assert created.json()["issue_url"] == "https://team.atlassian.net/browse/OPS-7"

    status = client.get("/api/jira/issues/OPS-7/status").json()
    assert status["status"] == "To Do"
    assert client.get("/api/jira/issues/bad-key/status").status_code == 400

    history = client.get("/api/jira/tickets").json()
    assert history[0]["issue_key"] == "OPS-7"

    disconnected = client.delete("/api/jira/connection").json()
    assert disconnected["configured"] is False


def test_jira_rejects_unsafe_site_urls(client: TestClient):
    response = client.post("/api/jira/connection", json={
        "site_url": "http://team.atlassian.net", "email": "dev@example.com", "api_token": "api-token-abcdef12"})
    assert response.status_code == 400
    bad_email = client.post("/api/jira/connection", json={
        "site_url": "https://team.atlassian.net", "email": "not-an-email", "api_token": "api-token-abcdef12"})
    assert bad_email.status_code == 422


def test_frontend_fallback_and_api_404s(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200
    assert "RepoMind AI" in page.text
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "RepoMind AI"
