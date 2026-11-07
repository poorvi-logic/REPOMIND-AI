from __future__ import annotations

import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.index import RepositoryIndex
from app.ingestion import IngestionLimits
from app.intelligence import MODE_GUIDE
from app.main import create_app
from app.pipeline import analyze_directory
from tests.conftest import PROJECT_ROOT, SAMPLE_DIR, build_zip, make_settings
from tests.fakes import FakeLLM


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path / "data")))


def _upload(client: TestClient, archive: Path) -> str:
    with archive.open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")})
    assert response.status_code == 201, response.text
    return response.json()["analysis_id"]


def _sample_zip(tmp_path: Path) -> Path:
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(SAMPLE_DIR.rglob("*.py")):
            bundle.write(path, arcname=path.relative_to(SAMPLE_DIR).as_posix())
    return archive


def _index(path: Path) -> RepositoryIndex:
    return RepositoryIndex(analyze_directory(path, analysis_id="assistant0001", repository_name="t",
                                             source_type="local", source_ref="t", limits=IngestionLimits()))


def _events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_conversation_keeps_history_and_uses_it_for_follow_up_questions(client: TestClient, tmp_path: Path):
    analysis_id = _upload(client, _sample_zip(tmp_path))
    fake = FakeLLM(reply="Payment is checked by validate_payment [S1].")
    client.app.state.services.llm = fake
    conversation = client.post(f"/api/analyses/{analysis_id}/conversations", json={}).json()
    first = client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/messages",
                        json={"question": "Where is payment validation implemented?"})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/messages",
                         json={"question": "And what does it return?"})
    assert second.status_code == 200
    follow_up_prompt = fake.calls[-1][1]
    assert "Conversation so far" in follow_up_prompt
    assert "Where is payment validation implemented?" in follow_up_prompt
    detail = client.get(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}").json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["title"] == "Where is payment validation implemented?"


def test_answer_mode_changes_the_instructions_sent_to_the_model(client: TestClient, tmp_path: Path):
    analysis_id = _upload(client, _sample_zip(tmp_path))
    fake = FakeLLM(reply="It is handled in payment.py [S1].")
    client.app.state.services.llm = fake
    conversation = client.post(f"/api/analyses/{analysis_id}/conversations", json={}).json()
    client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/messages",
                json={"question": "Where is payment validation implemented?", "mode": "beginner"})
    assert MODE_GUIDE["beginner"] in fake.calls[-1][1]
    client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/messages",
                json={"question": "Where is payment validation implemented?", "mode": "deep_dive"})
    assert MODE_GUIDE["deep_dive"] in fake.calls[-1][1]


def test_streaming_emits_context_text_and_a_final_message_with_citations(client: TestClient, tmp_path: Path):
    analysis_id = _upload(client, _sample_zip(tmp_path))
    client.app.state.services.llm = FakeLLM(reply="Payment is validated by validate_payment [S1].")
    conversation = client.post(f"/api/analyses/{analysis_id}/conversations", json={}).json()
    response = client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/stream",
                           json={"question": "Where is payment validation implemented?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = _events(response)
    assert events[0]["type"] == "context" and events[0]["citations"]
    streamed = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "validate_payment" in streamed
    done = events[-1]
    assert done["type"] == "done"
    assert done["message"]["payload"]["citations"][0]["file"] == "payment.py"
    assert done["suggestions"]


def test_streaming_falls_back_when_the_model_fails_midway(client: TestClient, tmp_path: Path):
    analysis_id = _upload(client, _sample_zip(tmp_path))
    client.app.state.services.llm = FakeLLM(status="timeout")
    conversation = client.post(f"/api/analyses/{analysis_id}/conversations", json={}).json()
    events = _events(client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/stream",
                                 json={"question": "Where is payment validation implemented?"}))
    assert events[-1]["message"]["payload"]["ai_status"] == "api_error"
    assert events[-1]["message"]["payload"]["mode"] == "deterministic"


def test_conversations_are_isolated_between_projects(client: TestClient, tmp_path: Path):
    first = _upload(client, _sample_zip(tmp_path))
    other_archive = build_zip(tmp_path / "other.zip", {"other/app.py": "def other():\n    return 1\n"})
    second = _upload(client, other_archive)
    conversation = client.post(f"/api/analyses/{first}/conversations", json={}).json()
    assert client.get(f"/api/analyses/{second}/conversations/{conversation['id']}").status_code == 404
    assert client.get(f"/api/analyses/{second}/conversations").json() == []


def test_unsupported_question_is_stored_without_calling_the_model(client: TestClient, tmp_path: Path):
    analysis_id = _upload(client, _sample_zip(tmp_path))
    fake = FakeLLM()
    client.app.state.services.llm = fake
    conversation = client.post(f"/api/analyses/{analysis_id}/conversations", json={}).json()
    result = client.post(f"/api/analyses/{analysis_id}/conversations/{conversation['id']}/messages",
                         json={"question": "zebra quantum banana"}).json()
    assert result["message"]["payload"]["insufficient_evidence"] is True
    assert fake.calls == []


def test_text_and_import_search_cover_the_whole_project(sample_dir: Path):
    index = _index(sample_dir)
    text_hits = index.text_search("payment")
    assert {hit["file"] for hit in text_hits} >= {"payment.py", "orders.py"}
    assert all("payment" in hit["text"].lower() for hit in text_hits)
    import_hits = index.import_search("orders")
    assert any(hit["file"] == "main.py" and hit["statement"] == "from orders import OrderService" for hit in import_hits)


def test_overview_reports_complexity_size_and_language_coverage(tmp_path: Path):
    archive = build_zip(tmp_path / "mixed.zip", {
        "project/app.py": "def run(x):\n    if x:\n        return 1\n    return 2\n",
        "project/README.md": "# notes",
        "project/static/index.html": "<html></html>",
        "project/static/app.css": "body {}",
    })
    from app.ingestion import extract_python_archive, detect_repository_root
    report = extract_python_archive(archive, tmp_path / "out", IngestionLimits())
    root = detect_repository_root(tmp_path / "out")
    analysis = analyze_directory(root, analysis_id="mixedaid0001", repository_name="mixed", source_type="zip",
                                 source_ref="mixed.zip", limits=IngestionLimits(),
                                 other_file_types=report.other_file_types)
    coverage = analysis["summary"]["language_coverage"]
    assert coverage["analyzed"] == ["Python"]
    assert coverage["not_analyzed"] == {".html": 1, ".md": 1, ".css": 1}
    index = RepositoryIndex(analysis)
    overview = index.summary()
    assert overview["most_complex"][0]["qualname"] == "run"
    assert overview["largest_files"][0]["path"] == "app.py"


def test_duplicate_bodies_and_unused_functions_are_reported_once(tmp_path: Path):
    body = "    total = 0\n    for item in items:\n        total += item\n    print(total)\n    return total\n"
    (tmp_path / "first.py").write_text(f"def sum_a(items):\n{body}", encoding="utf-8")
    (tmp_path / "second.py").write_text(f"def sum_b(items):\n{body}", encoding="utf-8")
    (tmp_path / "unused.py").write_text("def forgotten_helper():\n    return 42\n", encoding="utf-8")
    analysis = analyze_directory(tmp_path, analysis_id="dupaid000001", repository_name="d", source_type="local",
                                 source_ref="d", limits=IngestionLimits())
    duplicates = [f for f in analysis["findings"] if f["rule_id"] == "RM-DUP-001"]
    assert len(duplicates) == 1
    assert "second.py" in duplicates[0]["explanation"] or "second.py" in duplicates[0]["evidence"]
    unused = [f for f in analysis["findings"] if f["rule_id"] == "RM-DEAD-001"]
    assert {f["evidence"] for f in unused} == {
        "sum_a is never referenced by name",
        "sum_b is never referenced by name",
        "forgotten_helper is never referenced by name",
    }
    assert all(f["why_it_matters"] for f in analysis["findings"])


def test_mcp_status_reports_every_registered_tool(client: TestClient):
    status = client.get("/api/mcp/status").json()
    assert status["ready"] is True
    assert status["tools_registered"] == status["tools_expected"] == 8
    assert status["missing"] == []


def test_mcp_server_responds_to_a_real_client_over_stdio(sample_dir: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run() -> tuple[list[str], dict]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],
                                       cwd=str(PROJECT_ROOT), env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool("scan_repository", {"repository_path": str(sample_dir)})
                return sorted(tool.name for tool in listed.tools), json.loads(result.content[0].text)

    names, payload = asyncio.run(run())
    assert len(names) == 8
    assert "scan_repository" in names and "ask_repository_question" in names
    assert payload["summary"]["python_files"] == 11
    assert payload.get("error") is None
