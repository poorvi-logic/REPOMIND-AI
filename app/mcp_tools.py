from __future__ import annotations

import copy
import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import NotFoundError
from .index import RepositoryIndex
from .ingestion import IngestionLimits, discover_python_files
from .intelligence import answer_question, explain_file, explain_symbol
from .llm import LLMClient
from .pipeline import analyze_directory
from .risks import SEVERITY_ORDER, summarize_findings
from .tickets import make_ticket_draft

MAX_QUERY_CHARS = 500
MAX_PATH_CHARS = 1000
MAX_NAME_CHARS = 300
SEVERITIES = tuple(SEVERITY_ORDER)

TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "scan_repository",
        "description": "Analyze the Python files in a local repository directory and return the summary, dependency "
                       "statistics, cycles and the highest-priority risk findings.",
        "parameters": [{"name": "repository_path", "type": "string", "required": True,
                        "description": "Absolute or relative path to a local repository directory."}],
    },
    {
        "name": "search_repository",
        "description": "Find source chunks relevant to a question or search terms, with file and line references.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "question_or_terms", "type": "string", "required": True, "description": "Search terms or a question."},
            {"name": "limit", "type": "integer", "required": False, "description": "Maximum results (1-25, default 8)."},
        ],
    },
    {
        "name": "get_function_details",
        "description": "Return a function or class's signature, decorators, complexity, source, confirmed and approximate "
                       "callers and callees, and related findings.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "function_name", "type": "string", "required": True,
             "description": "Function name, qualified name such as Class.method, or symbol id."},
            {"name": "file_path", "type": "string", "required": False, "description": "Restrict the lookup to one file."},
        ],
    },
    {
        "name": "get_dependency_map",
        "description": "Return the module dependency map or the function call map, optionally for one module. Each "
                       "relationship is labelled confirmed, approximate, external or unresolved.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "scope", "type": "string", "required": False, "description": "'modules' (default) or 'functions'."},
            {"name": "module", "type": "string", "required": False, "description": "Dotted module name for a focused view."},
            {"name": "confidence", "type": "string", "required": False, "description": "'confirmed' (default) or 'all'."},
            {"name": "limit", "type": "integer", "required": False, "description": "Maximum nodes (10-500, default 100)."},
        ],
    },
    {
        "name": "analyze_repository_risks",
        "description": "List heuristic review findings with rule ID, severity, file, line, redacted evidence, explanation "
                       "and remediation. Findings are review suggestions, not confirmed vulnerabilities.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "min_severity", "type": "string", "required": False, "description": "high, medium, low or info (default low)."},
            {"name": "category", "type": "string", "required": False, "description": "Optional category filter."},
            {"name": "limit", "type": "integer", "required": False, "description": "Maximum findings returned (default 50)."},
        ],
    },
    {
        "name": "explain_code",
        "description": "Explain a file or a function. Uses an OpenAI model when OPENAI_API_KEY is set, otherwise returns a "
                       "deterministic summary built from static analysis.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "file_path", "type": "string", "required": True, "description": "Relative path of the file."},
            {"name": "function_name", "type": "string", "required": False, "description": "Optional function or class to explain."},
        ],
    },
    {
        "name": "ask_repository_question",
        "description": "Answer a question using only retrieved repository source, with file and line citations. Returns an "
                       "insufficient-evidence result instead of guessing.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "question", "type": "string", "required": True, "description": "Natural-language question about the code."},
        ],
    },
    {
        "name": "prepare_jira_ticket",
        "description": "Build a Jira issue preview (summary, labels, description) from a finding. The ticket is not "
                       "created; creation requires the RepoMind web interface with explicit confirmation.",
        "parameters": [
            {"name": "repository_path", "type": "string", "required": True, "description": "Local repository directory."},
            {"name": "finding_id", "type": "string", "required": True, "description": "Finding identifier from analyze_repository_risks."},
            {"name": "project_key", "type": "string", "required": False, "description": "Jira project key for the preview."},
        ],
    },
]


def tool_catalog() -> list[dict[str, Any]]:
    return copy.deepcopy(TOOL_CATALOG)


class ToolInputError(ValueError):
    pass


def _text(value: Any, name: str, max_length: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ToolInputError(f"{name} must be a string.")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ToolInputError(f"{name} must not be empty.")
    if len(cleaned) > max_length:
        raise ToolInputError(f"{name} must be at most {max_length} characters.")
    return cleaned


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{name} must be an integer.")
    if not minimum <= value <= maximum:
        raise ToolInputError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _compact_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {key: finding[key] for key in ("id", "rule_id", "title", "category", "severity", "confidence",
                                          "file", "line", "evidence", "explanation", "remediation")}


class McpToolkit:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self._allowed_roots = settings.mcp_allowed_roots
        self._limits = IngestionLimits(
            max_python_files=settings.max_python_files,
            max_file_bytes=settings.max_file_kb * 1024,
            max_repository_bytes=settings.max_repository_mb * 1024 * 1024,
        )
        self.llm = llm or LLMClient(settings.openai_api_key, settings.openai_model,
                                    settings.openai_embedding_model, settings.openai_timeout_seconds)
        self._cache: dict[str, tuple[str, RepositoryIndex]] = {}
        self._lock = threading.Lock()

    def resolve_repository(self, repository_path: Any) -> Path:
        raw = _text(repository_path, "repository_path", MAX_PATH_CHARS)
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ToolInputError("repository_path must be an existing directory.")
        if self._allowed_roots and not any(path == root or root in path.parents for root in self._allowed_roots):
            raise ToolInputError("repository_path is outside the directories allowed by REPOMIND_MCP_ALLOWED_ROOTS.")
        return path

    def index_for(self, repository_path: Any) -> RepositoryIndex:
        path = self.resolve_repository(repository_path)
        sources, _ = discover_python_files(path, self._limits)
        fingerprint_material = "|".join(
            f"{source.relative_path}:{source.size_bytes}:{source.path.stat().st_mtime_ns}" for source in sources
        )
        fingerprint = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()
        key = str(path)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == fingerprint:
                return cached[1]
        analysis = analyze_directory(
            path, analysis_id="local-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10],
            repository_name=path.name, source_type="local", source_ref=path.name, limits=self._limits,
        )
        if analysis["summary"]["python_files"] == 0:
            raise ToolInputError("No Python files were found in repository_path.")
        index = RepositoryIndex(analysis)
        with self._lock:
            self._cache[key] = (fingerprint, index)
        return index

    def scan_repository(self, repository_path: str) -> dict[str, Any]:
        index = self.index_for(repository_path)
        findings = index.risks("info")
        return {
            "repository": index.analysis["repository"],
            "summary": index.analysis["summary"],
            "dependency_summary": index.analysis["dependency_summary"],
            "cycles": index.cycles[:20],
            "top_findings": [_compact_finding(item) for item in findings[:30]],
            "findings_total": len(findings),
            "note": "Call relationships are static. Confirmed, approximate, external and unresolved labels are provided.",
        }

    def search_repository(self, repository_path: str, question_or_terms: str, limit: int = 8) -> dict[str, Any]:
        query = _text(question_or_terms, "question_or_terms", MAX_QUERY_CHARS)
        size = _integer(limit, "limit", 1, 25)
        index = self.index_for(repository_path)
        hits = index.search(query, limit=size)
        return {
            "query": query,
            "insufficient_evidence": not hits,
            "results": [{key: hit[key] for key in ("file", "line", "end_line", "symbol", "score", "matched_terms", "snippet")}
                        for hit in hits],
        }

    def get_function_details(self, repository_path: str, function_name: str, file_path: str | None = None) -> dict[str, Any]:
        name = _text(function_name, "function_name", MAX_NAME_CHARS)
        file_filter = _text(file_path, "file_path", MAX_PATH_CHARS) if file_path else None
        index = self.index_for(repository_path)
        matches = index.resolve_symbols(name, file_filter)
        if not matches:
            return {"found": False, "message": f"No function or class named '{name}' was found."}
        if len(matches) > 1:
            return {"found": True, "ambiguous": True,
                    "message": "Several symbols match. Pass file_path or a qualified name.",
                    "candidates": [{"id": m["id"], "qualname": m["qualname"], "file": m["file"], "line": m["line"]}
                                   for m in matches[:10]]}
        detail = index.symbol_detail(matches[0]["id"])
        detail["source"]["text"] = "\n".join(detail["source"]["text"].splitlines()[:120])
        return {"found": True, "ambiguous": False, "symbol": detail}

    def get_dependency_map(self, repository_path: str, scope: str = "modules", module: str | None = None,
                           confidence: str = "confirmed", limit: int = 100) -> dict[str, Any]:
        if scope not in {"modules", "functions"}:
            raise ToolInputError("scope must be 'modules' or 'functions'.")
        if confidence not in {"confirmed", "all"}:
            raise ToolInputError("confidence must be 'confirmed' or 'all'.")
        size = _integer(limit, "limit", 10, 500)
        index = self.index_for(repository_path)
        if module:
            module_name = _text(module, "module", MAX_NAME_CHARS)
            if module_name not in index.module_to_file:
                raise NotFoundError(f"Module '{module_name}' was not found.")
            return index.dependency_summary_for_module(module_name)
        graph = index.dependency_graph(scope, confidence, max_nodes=size)
        return {
            "scope": scope,
            "confidence": confidence,
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "truncated": graph["truncated"],
            "cycles": index.cycles,
            "summary": index.analysis["dependency_summary"],
        }

    def analyze_repository_risks(self, repository_path: str, min_severity: str = "low",
                                 category: str | None = None, limit: int = 50) -> dict[str, Any]:
        severity = _text(min_severity, "min_severity", 10)
        if severity not in SEVERITIES:
            raise ToolInputError("min_severity must be one of high, medium, low or info.")
        size = _integer(limit, "limit", 1, 500)
        category_filter = _text(category, "category", 60) if category else None
        index = self.index_for(repository_path)
        findings = index.risks(severity, category_filter)
        return {
            "total": len(findings),
            "summary": summarize_findings(findings),
            "findings": [_compact_finding(item) for item in findings[:size]],
            "disclaimer": "Heuristic review suggestions. These are not confirmed vulnerabilities.",
        }

    def explain_code(self, repository_path: str, file_path: str, function_name: str | None = None) -> dict[str, Any]:
        path_text = _text(file_path, "file_path", MAX_PATH_CHARS)
        index = self.index_for(repository_path)
        if function_name:
            matches = index.resolve_symbols(_text(function_name, "function_name", MAX_NAME_CHARS), path_text)
            if not matches:
                raise NotFoundError("Function or class not found in that file.")
            result = explain_symbol(index, matches[0]["id"], self.llm)
        else:
            result = explain_file(index, path_text, self.llm)
        return {"file": path_text, "function": function_name, **result}

    def ask_repository_question(self, repository_path: str, question: str) -> dict[str, Any]:
        text = _text(question, "question", 2000)
        index = self.index_for(repository_path)
        hits = index.search(text, limit=8)
        answer = answer_question(index, text, hits, self.llm, "lexical")
        return {
            "question": text,
            "answer": answer["answer"],
            "mode": answer["mode"],
            "ai_status": answer["ai_status"],
            "insufficient_evidence": answer["insufficient_evidence"],
            "citations": answer.get("citations", []),
            "evidence": [{key: hit[key] for key in ("file", "line", "end_line", "symbol", "snippet")} for hit in hits[:5]],
            "graph_facts": answer["graph_facts"],
        }

    def prepare_jira_ticket(self, repository_path: str, finding_id: str, project_key: str = "") -> dict[str, Any]:
        identifier = _text(finding_id, "finding_id", 120)
        project = _text(project_key, "project_key", 10, allow_empty=True)
        index = self.index_for(repository_path)
        try:
            finding = index.finding(identifier)
        except NotFoundError as exc:
            raise ToolInputError("finding_id was not found. Run analyze_repository_risks to list identifiers.") from exc
        draft = make_ticket_draft(finding, index.analysis["repository"], index.analysis_id, project)
        return {**draft, "created": False, "note": "Preview only. Create the issue from the RepoMind Jira page."}
