from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.mcp_tools import TOOL_CATALOG, McpToolkit, ToolInputError
from tests.conftest import make_settings
from tests.fakes import FakeLLM


@pytest.fixture
def toolkit(settings: Settings) -> McpToolkit:
    return McpToolkit(settings, llm=FakeLLM(enabled=False))


def test_catalog_lists_the_eight_required_tools():
    names = [item["name"] for item in TOOL_CATALOG]
    assert names == [
        "scan_repository", "search_repository", "get_function_details", "get_dependency_map",
        "analyze_repository_risks", "explain_code", "ask_repository_question", "prepare_jira_ticket",
    ]
    assert all(item["description"] and item["parameters"] for item in TOOL_CATALOG)


def test_scan_repository_returns_summary_and_labelled_dependencies(toolkit, sample_dir):
    result = toolkit.scan_repository(str(sample_dir))
    assert result["summary"]["python_files"] == 11
    assert result["cycles"]
    assert "Confirmed" in result["note"] or "static" in result["note"]
    assert result["top_findings"][0]["severity"] == "high"


def test_search_repository_returns_citations_and_insufficient_flag(toolkit, sample_dir):
    found = toolkit.search_repository(str(sample_dir), "payment validation", limit=3)
    assert found["insufficient_evidence"] is False
    assert found["results"][0]["file"] == "payment.py"
    missing = toolkit.search_repository(str(sample_dir), "zebra quantum", limit=3)
    assert missing["insufficient_evidence"] is True


def test_function_details_resolve_qualified_names_and_report_ambiguity(toolkit, sample_dir):
    detail = toolkit.get_function_details(str(sample_dir), "OrderService.refund")
    assert detail["found"] is True and detail["symbol"]["qualname"] == "OrderService.refund"
    ambiguous = toolkit.get_function_details(str(sample_dir), "__init__")
    assert ambiguous["found"] is True and ambiguous["ambiguous"] is True
    absent = toolkit.get_function_details(str(sample_dir), "does_not_exist")
    assert absent["found"] is False


def test_dependency_map_supports_modules_functions_and_focus(toolkit, sample_dir):
    modules = toolkit.get_dependency_map(str(sample_dir), scope="modules")
    assert any(node["id"] == "orders" for node in modules["nodes"])
    focused = toolkit.get_dependency_map(str(sample_dir), module="orders")
    assert "imported_by" in focused
    with pytest.raises(Exception):
        toolkit.get_dependency_map(str(sample_dir), module="no_such_module")
    with pytest.raises(ToolInputError):
        toolkit.get_dependency_map(str(sample_dir), scope="weird")


def test_risk_analysis_filters_by_severity_and_returns_disclaimer(toolkit, sample_dir):
    result = toolkit.analyze_repository_risks(str(sample_dir), min_severity="high")
    assert result["total"] >= 3
    assert all(item["severity"] == "high" for item in result["findings"])
    assert "not confirmed vulnerabilities" in result["disclaimer"]
    with pytest.raises(ToolInputError):
        toolkit.analyze_repository_risks(str(sample_dir), min_severity="critical")


def test_explain_code_without_ai_is_deterministic(toolkit, sample_dir):
    result = toolkit.explain_code(str(sample_dir), "payment.py")
    assert result["mode"] == "deterministic"
    fn = toolkit.explain_code(str(sample_dir), "main.py", function_name="checkout")
    assert "checkout" in fn["text"]


def test_question_answer_is_grounded_or_declined(toolkit, sample_dir):
    answered = toolkit.ask_repository_question(str(sample_dir), "Where is payment validation implemented?")
    assert answered["evidence"] and answered["mode"] == "deterministic"
    declined = toolkit.ask_repository_question(str(sample_dir), "zebra quantum banana")
    assert declined["insufficient_evidence"] is True
    assert declined["mode"] == "insufficient-evidence"


def test_prepare_jira_ticket_previews_without_creating(toolkit, sample_dir):
    findings = toolkit.analyze_repository_risks(str(sample_dir), min_severity="high")["findings"]
    preview = toolkit.prepare_jira_ticket(str(sample_dir), findings[0]["id"], "OPS")
    assert preview["created"] is False
    assert preview["project"] == "OPS"
    assert preview["summary"].startswith("[RepoMind]")
    with pytest.raises(ToolInputError):
        toolkit.prepare_jira_ticket(str(sample_dir), "RM-NOPE-000")


@pytest.mark.parametrize("call", [
    lambda t, d: t.scan_repository(""),
    lambda t, d: t.scan_repository("/definitely/not/a/real/path"),
    lambda t, d: t.search_repository(str(d), "", 5),
    lambda t, d: t.search_repository(str(d), "x" * 600, 5),
    lambda t, d: t.search_repository(str(d), "payment", 0),
    lambda t, d: t.search_repository(str(d), "payment", "5"),
    lambda t, d: t.get_function_details(str(d), ""),
    lambda t, d: t.explain_code(str(d), ""),
    lambda t, d: t.ask_repository_question(str(d), "   "),
])
def test_invalid_inputs_raise_tool_input_errors(toolkit, sample_dir, call):
    with pytest.raises((ToolInputError, Exception)) as info:
        call(toolkit, sample_dir)
    assert isinstance(info.value, Exception)


def test_repository_path_must_be_a_directory(toolkit, sample_dir):
    with pytest.raises(ToolInputError, match="existing directory"):
        toolkit.scan_repository(str(sample_dir / "payment.py"))


def test_allowed_roots_restrict_which_directories_can_be_scanned(tmp_path, sample_dir):
    settings = make_settings(tmp_path / "data", mcp_allowed_roots=(tmp_path.resolve(),))
    restricted = McpToolkit(settings, llm=FakeLLM(enabled=False))
    with pytest.raises(ToolInputError, match="REPOMIND_MCP_ALLOWED_ROOTS"):
        restricted.scan_repository(str(sample_dir))


def test_repeated_scans_reuse_cache_until_files_change(toolkit, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    first = toolkit.index_for(str(repo))
    assert toolkit.index_for(str(repo)) is first
    (repo / "app.py").write_text("def one():\n    return 1\n\ndef two():\n    return 2\n", encoding="utf-8")
    refreshed = toolkit.index_for(str(repo))
    assert refreshed is not first
    assert refreshed.analysis["summary"]["functions"] == 2


def test_empty_repository_is_reported(toolkit, tmp_path):
    (tmp_path / "notes.txt").write_text("nothing", encoding="utf-8")
    with pytest.raises(ToolInputError, match="No Python files"):
        toolkit.scan_repository(str(tmp_path))


def test_mcp_server_registers_all_tools_and_returns_json_errors(tmp_path, monkeypatch, sample_dir):
    import app.mcp_server as server

    tools = asyncio.run(server.mcp.list_tools())
    assert sorted(tool.name for tool in tools) == sorted(item["name"] for item in TOOL_CATALOG)

    monkeypatch.setattr(server, "_toolkit", McpToolkit(make_settings(tmp_path / "data"), llm=FakeLLM(enabled=False)))
    error = json.loads(server.scan_repository("/no/such/path"))
    assert "existing directory" in error["error"]
    ok = json.loads(server.scan_repository(str(sample_dir)))
    assert ok["summary"]["python_files"] == 11
    monkeypatch.setattr(server, "_toolkit", None)
