from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.errors import ExternalServiceError, InputError, NotFoundError
from app.jira import (
    JiraClient, JiraCredentialStore, JiraCredentials, credentials_from_settings, normalize_site_url,
)
from app.tickets import build_adf_description, make_ticket_draft
from tests.conftest import make_settings

FINDING = {
    "id": "RM-SEC-002-abcd1234", "rule_id": "RM-SEC-002", "title": "Subprocess call may run through the shell",
    "category": "command-execution", "severity": "high", "confidence": "heuristic", "file": "reports.py", "line": 8,
    "end_line": 8, "evidence": "subprocess.run(command, shell=True)",
    "explanation": "shell=True passes the command through a shell.",
    "remediation": "Pass a list of arguments.",
}
CREDENTIALS = JiraCredentials(base_url="https://team.atlassian.net", email="dev@example.com", api_token="tok-secret-123456")


def _client(handler) -> JiraClient:
    return JiraClient(CREDENTIALS, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("raw", [
    "https://team.atlassian.net", "https://team.atlassian.net/", "https://TEAM.atlassian.net:443",
])
def test_site_urls_are_normalised(raw):
    assert normalize_site_url(raw, allow_any_host=False) == "https://team.atlassian.net"


@pytest.mark.parametrize("raw", [
    "http://team.atlassian.net", "https://example.com", "https://team.atlassian.net/jira",
    "https://user:pw@team.atlassian.net", "https://team.atlassian.net?x=1", "",
])
def test_unsafe_site_urls_are_rejected(raw):
    with pytest.raises(InputError):
        normalize_site_url(raw, allow_any_host=False)


def test_custom_hosts_require_explicit_opt_in():
    assert normalize_site_url("https://jira.internal.example", allow_any_host=True) == "https://jira.internal.example"
    with pytest.raises(InputError):
        normalize_site_url("https://jira.internal.example", allow_any_host=False)


def test_environment_credentials_are_loaded_and_normalised(tmp_path):
    settings = make_settings(tmp_path, jira_base_url="https://team.atlassian.net/", jira_email="a@b.co",
                             jira_api_token="token-value-123")
    credentials = credentials_from_settings(settings)
    assert credentials.base_url == "https://team.atlassian.net"
    assert credentials_from_settings(make_settings(tmp_path)) is None


def test_session_credentials_take_precedence_and_status_hides_token():
    store = JiraCredentialStore(JiraCredentials("https://env.atlassian.net", "env@x.co", "env-token-value"))
    assert store.current()[1] == "environment"
    store.set_session(CREDENTIALS)
    assert store.current() == (CREDENTIALS, "session")
    status = store.public_status()
    assert status["source"] == "session"
    assert "tok-secret" not in json.dumps(status)
    store.clear_session()
    assert store.current()[1] == "environment"


def test_token_is_excluded_from_credential_repr():
    assert "tok-secret-123456" not in repr(CREDENTIALS)


def test_myself_authenticates_with_basic_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json={"accountId": "acc-1", "displayName": "Dev", "active": True})

    identity = _client(handler).myself()
    assert identity == {"account_id": "acc-1", "display_name": "Dev", "active": True}
    assert seen["path"] == "/rest/api/3/myself"
    assert seen["auth"].startswith("Basic ")


def test_projects_and_issue_types_are_listed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/project/search":
            return httpx.Response(200, json={"values": [{"key": "OPS", "name": "Operations", "id": "10001"}]})
        return httpx.Response(200, json={"issueTypes": [{"name": "Task"}, {"name": "Sub-task", "subtask": True}]})

    client = _client(handler)
    assert client.projects() == [{"key": "OPS", "name": "Operations", "id": "10001"}]
    assert client.issue_types("OPS") == ["Task"]


def test_create_issue_sends_atlassian_document_format_description():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "10042", "key": "OPS-42", "self": "https://x"})

    draft = make_ticket_draft(FINDING, "sample", "abc123def456", "OPS")
    created = _client(handler).create_issue({
        "project": {"key": "OPS"}, "issuetype": {"name": "Task"}, "summary": draft["summary"],
        "description": draft["description_adf"], "labels": draft["labels"],
    })
    assert created["key"] == "OPS-42"
    assert created["url"] == "https://team.atlassian.net/browse/OPS-42"
    fields = captured["body"]["fields"]
    assert fields["project"] == {"key": "OPS"}
    assert fields["description"]["type"] == "doc" and fields["description"]["version"] == 1
    code_blocks = [node for node in fields["description"]["content"] if node["type"] == "codeBlock"]
    assert code_blocks and code_blocks[0]["content"][0]["text"] == FINDING["evidence"]
    assert all(" " not in label for label in fields["labels"])


def test_issue_status_is_returned_for_display():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"key": "OPS-42", "fields": {
            "summary": "Fix", "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "priority": {"name": "High"}, "assignee": {"displayName": "Dev"}, "updated": "2026-01-01T00:00:00.000+0000",
        }})

    status = _client(handler).issue_status("OPS-42")
    assert status["status"] == "In Progress"
    assert status["url"].endswith("/browse/OPS-42")


@pytest.mark.parametrize("code, error_type", [(401, InputError), (403, InputError), (404, NotFoundError), (500, ExternalServiceError)])
def test_http_errors_map_to_service_errors_without_leaking_token(code, error_type):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"errorMessages": ["something went wrong"]})

    with pytest.raises(error_type) as info:
        _client(handler).myself()
    assert "tok-secret" not in str(info.value)


def test_network_failure_is_reported_as_external_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ExternalServiceError):
        _client(handler).myself()


def test_timeout_is_reported_as_external_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ExternalServiceError, match="did not respond"):
        _client(handler).myself()


def test_ticket_draft_contains_required_fields_and_heuristic_warning():
    draft = make_ticket_draft(FINDING, "sample", "abc123def456", "OPS")
    assert draft["project"] == "OPS"
    assert draft["summary"].startswith("[RepoMind] RM-SEC-002")
    assert "severity-high" in draft["labels"]
    assert "not proof of a defect" in draft["description"]
    assert "reports.py" in draft["description"] and "Line number: 8" in draft["description"]


def test_info_findings_produce_a_triage_warning():
    draft = make_ticket_draft({**FINDING, "severity": "info", "rule_id": "STY-001"}, "sample", "x", "OPS")
    assert draft["warnings"]


def test_adf_structure_is_valid_document_format():
    adf = build_adf_description(FINDING, "sample", "abc")
    assert adf["type"] == "doc"
    assert all("type" in node for node in adf["content"])
    assert any(node["type"] == "bulletList" for node in adf["content"])


def test_credential_store_defaults_to_unconfigured(tmp_path):
    settings = Settings(**{**make_settings(tmp_path).__dict__})
    assert credentials_from_settings(settings) is None
