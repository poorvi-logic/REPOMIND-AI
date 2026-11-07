from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dependencies import build_dependency_graph
from .extractor import extract_structure, is_package_file, module_name_for, parse_source
from .ingestion import IngestionLimits, detect_source_roots, discover_python_files
from .retrieval import build_chunks
from collections import Counter

from .risks import (
    IDENTIFIER_PATTERN, SEVERITY_ORDER, analyze_risks, body_fingerprints, duplicate_findings,
    summarize_findings, unused_function_findings,
)

SYMBOL_KINDS_WITH_BODY = frozenset({"function", "method", "nested_function", "class"})


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _enclosing_symbol_id(symbols: list[dict[str, Any]], line: int) -> str | None:
    candidates = [item for item in symbols if item["start_line"] <= line <= item["end_line"]]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item["length"])["id"]


def _unique_finding_ids(findings: list[dict[str, Any]]) -> None:
    seen: dict[str, int] = {}
    for finding in findings:
        count = seen.get(finding["id"], 0)
        seen[finding["id"]] = count + 1
        if count:
            finding["id"] = f"{finding['id']}-{count + 1}"


def analyze_directory(root: Path, *, analysis_id: str, repository_name: str, source_type: str,
                      source_ref: str, limits: IngestionLimits, warnings: list[str] | None = None,
                      commit: str | None = None, other_file_types: dict[str, int] | None = None) -> dict[str, Any]:
    sources, discovery_warnings = discover_python_files(root, limits)
    package_roots = detect_source_roots(root)
    all_warnings = [*(warnings or []), *discovery_warnings]
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    module_scopes: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    fingerprints: list[dict[str, Any]] = []
    identifier_counts: Counter = Counter()
    for source in sources:
        text = _read_text(source.path)
        identifier_counts.update(IDENTIFIER_PATTERN.findall(text))
        lines = text.splitlines()
        tree, parse_error = parse_source(text, source.relative_path)
        if tree is not None:
            structure = extract_structure(tree, source.relative_path, package_roots)
        else:
            structure = {
                "module": module_name_for(source.relative_path, package_roots),
                "is_package": is_package_file(source.relative_path),
                "imports": [], "symbols": [], "module_calls": [],
            }
        file_symbols = structure["symbols"]
        symbols.extend(file_symbols)
        module_scopes.append({
            "id": f"{source.relative_path}::<module>", "file": source.relative_path,
            "module": structure["module"], "qualname": "<module>", "name": "<module>", "kind": "module",
            "class_name": None, "is_nested": False, "is_async": False, "method_type": None,
            "line": 0, "start_line": 0, "end_line": 0, "length": 0, "complexity": 1,
            "decorators": [], "arguments": [], "returns": None, "docstring": None, "bases": [],
            "calls": structure["module_calls"],
        })
        if tree is not None:
            file_findings = analyze_risks(tree, source.relative_path, lines, file_symbols)
            findings.extend(file_findings)
            fingerprints.extend(body_fingerprints(tree, source.relative_path))
        chunks.extend(build_chunks(source.relative_path, lines, file_symbols, parse_error is None))
        files.append({
            "path": source.relative_path,
            "module": structure["module"],
            "is_package": structure["is_package"],
            "lines": len(lines),
            "size_bytes": source.size_bytes,
            "parse_error": parse_error,
            "imports": structure["imports"],
            "content": text,
        })

    findings.extend(duplicate_findings(fingerprints))
    findings.extend(unused_function_findings(symbols, identifier_counts))
    graph = build_dependency_graph(files, symbols, module_scopes)
    symbol_lookup = {item["path"]: [] for item in files}
    for symbol in symbols:
        symbol_lookup.setdefault(symbol["file"], []).append(symbol)
    for finding in findings:
        finding["symbol_id"] = _enclosing_symbol_id(symbol_lookup.get(finding["file"], []), finding["line"])
    findings.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["file"], item["line"]))
    _unique_finding_ids(findings)

    findings_summary = summarize_findings(findings)
    dependency_summary = graph["summary"]
    summary = {
        "python_files": len(files),
        "total_lines": sum(item["lines"] for item in files),
        "classes": sum(1 for item in symbols if item["kind"] == "class"),
        "functions": sum(1 for item in symbols if item["kind"] in {"function", "method", "nested_function"}),
        "methods": sum(1 for item in symbols if item["kind"] == "method"),
        "imports": sum(len(item["imports"]) for item in files),
        "findings": len(findings),
        "parse_errors": sum(1 for item in files if item["parse_error"]),
        "module_dependencies": dependency_summary["module_dependencies"],
        "external_dependencies": dependency_summary["external_dependencies"],
        "call_relationships": dependency_summary["call_relationships"],
        "circular_dependencies": dependency_summary["circular_dependencies"],
        "findings_by_severity": findings_summary["by_severity"],
        "findings_by_category": findings_summary["by_category"],
        "language_coverage": {
            "analyzed": ["Python"],
            "python_files": len(files),
            "not_analyzed": dict(sorted((other_file_types or {}).items(), key=lambda item: (-item[1], item[0]))),
        },
        "warnings": all_warnings,
    }
    edges = [*graph["module_edges"], *graph["call_edges"], *graph["contains_edges"]]
    return {
        "analysis_id": analysis_id,
        "repository": repository_name,
        "source_type": source_type,
        "source_ref": source_ref,
        "commit": commit,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "warnings": all_warnings,
        "files": files,
        "symbols": symbols + module_scopes,
        "edges": edges,
        "cycles": graph["cycles"],
        "unresolved_references": graph["unresolved_references"],
        "dependency_summary": dependency_summary,
        "findings": findings,
        "chunks": chunks,
    }


def new_analysis_id(seed: str | None = None) -> str:
    material = f"{seed or ''}{datetime.now(timezone.utc).isoformat()}{id(object())}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]


def analyze_repository(root: Path, max_files: int = 500) -> dict[str, Any]:
    resolved = Path(root).resolve()
    result = analyze_directory(
        resolved, analysis_id=new_analysis_id(str(resolved)), repository_name=resolved.name,
        source_type="local", source_ref=resolved.name, limits=IngestionLimits(max_python_files=max_files),
    )
    result["function_relationships"] = [edge for edge in result["edges"] if edge["kind"] == "calls"]
    return result
