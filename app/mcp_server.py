from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .config import load_settings
from .errors import RepoMindError
from .mcp_tools import TOOL_CATALOG, McpToolkit, ToolInputError

mcp = FastMCP("RepoMind AI")
_toolkit: McpToolkit | None = None
_DESCRIPTIONS = {item["name"]: item["description"] for item in TOOL_CATALOG}


def get_toolkit() -> McpToolkit:
    global _toolkit
    if _toolkit is None:
        _toolkit = McpToolkit(load_settings())
    return _toolkit


def _call(method: str, **kwargs: object) -> str:
    try:
        payload = getattr(get_toolkit(), method)(**kwargs)
    except (ToolInputError, RepoMindError) as exc:
        payload = {"error": str(exc)}
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


@mcp.tool(name="scan_repository", description=_DESCRIPTIONS["scan_repository"])
def scan_repository(repository_path: str) -> str:
    return _call("scan_repository", repository_path=repository_path)


@mcp.tool(name="search_repository", description=_DESCRIPTIONS["search_repository"])
def search_repository(repository_path: str, question_or_terms: str, limit: int = 8) -> str:
    return _call("search_repository", repository_path=repository_path, question_or_terms=question_or_terms, limit=limit)


@mcp.tool(name="get_function_details", description=_DESCRIPTIONS["get_function_details"])
def get_function_details(repository_path: str, function_name: str, file_path: str | None = None) -> str:
    return _call("get_function_details", repository_path=repository_path, function_name=function_name, file_path=file_path)


@mcp.tool(name="get_dependency_map", description=_DESCRIPTIONS["get_dependency_map"])
def get_dependency_map(repository_path: str, scope: str = "modules", module: str | None = None,
                       confidence: str = "confirmed", limit: int = 100) -> str:
    return _call("get_dependency_map", repository_path=repository_path, scope=scope, module=module,
                 confidence=confidence, limit=limit)


@mcp.tool(name="analyze_repository_risks", description=_DESCRIPTIONS["analyze_repository_risks"])
def analyze_repository_risks(repository_path: str, min_severity: str = "low", category: str | None = None,
                             limit: int = 50) -> str:
    return _call("analyze_repository_risks", repository_path=repository_path, min_severity=min_severity,
                 category=category, limit=limit)


@mcp.tool(name="explain_code", description=_DESCRIPTIONS["explain_code"])
def explain_code(repository_path: str, file_path: str, function_name: str | None = None) -> str:
    return _call("explain_code", repository_path=repository_path, file_path=file_path, function_name=function_name)


@mcp.tool(name="ask_repository_question", description=_DESCRIPTIONS["ask_repository_question"])
def ask_repository_question(repository_path: str, question: str) -> str:
    return _call("ask_repository_question", repository_path=repository_path, question=question)


@mcp.tool(name="prepare_jira_ticket", description=_DESCRIPTIONS["prepare_jira_ticket"])
def prepare_jira_ticket(repository_path: str, finding_id: str, project_key: str = "") -> str:
    return _call("prepare_jira_ticket", repository_path=repository_path, finding_id=finding_id, project_key=project_key)


if __name__ == "__main__":
    mcp.run()
