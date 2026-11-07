from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_VERSION = "2.0"
DISCLAIMER = (
    "Static analysis report. Call relationships are labelled confirmed, approximate, external or unresolved. "
    "Risk findings are heuristic review suggestions and are not confirmed vulnerabilities. Source code content is "
    "not included in this report."
)


def build_report(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "analysis": {
            "analysis_id": analysis["analysis_id"],
            "repository": analysis["repository"],
            "source_type": analysis["source_type"],
            "source_ref": analysis["source_ref"],
            "commit": analysis.get("commit"),
            "created_at": analysis["created_at"],
        },
        "summary": analysis["summary"],
        "warnings": analysis["warnings"],
        "files": [
            {"path": item["path"], "module": item["module"], "lines": item["lines"], "size_bytes": item["size_bytes"],
             "parse_error": item["parse_error"], "imports": item["imports"]}
            for item in analysis["files"]
        ],
        "symbols": [
            {"id": item["id"], "file": item["file"], "qualname": item["qualname"], "kind": item["kind"],
             "class_name": item.get("class_name"), "is_async": item.get("is_async", False),
             "is_nested": item.get("is_nested", False), "line": item["line"], "end_line": item.get("end_line"),
             "complexity": item.get("complexity"), "decorators": item.get("decorators", []),
             "arguments": item.get("arguments", []), "returns": item.get("returns"),
             "call_count": len(item.get("calls", []))}
            for item in analysis["symbols"] if item["kind"] != "module"
        ],
        "dependencies": {
            "summary": analysis["dependency_summary"],
            "module_edges": [edge for edge in analysis["edges"] if edge["kind"] == "module_import"],
            "call_edges": [edge for edge in analysis["edges"] if edge["kind"] == "calls"],
            "cycles": analysis["cycles"],
            "unresolved_references": analysis["unresolved_references"],
        },
        "findings": analysis["findings"],
    }


def write_report(report: dict[str, Any], reports_dir: Path, analysis_id: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"repomind-{analysis_id}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
