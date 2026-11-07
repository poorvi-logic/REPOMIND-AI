from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile
from fastapi.responses import FileResponse

from ..errors import NotFoundError
from ..schemas import (
    AskRequest, FileExplainRequest, FindingExplainRequest, FlowExplainRequest, GitHubAnalysisRequest,
    ModuleExplainRequest, SymbolExplainRequest,
)
from ..services import AppServices
from .deps import ANALYSIS_ID_PATTERN, get_services

router = APIRouter(prefix="/api/analyses", tags=["Analyses"])
AnalysisId = Annotated[str, Path(pattern=ANALYSIS_ID_PATTERN, description="12-character analysis identifier")]
Services = Annotated[AppServices, Depends(get_services)]
SeverityFilter = Literal["high", "medium", "low", "info"]


@router.post("/upload", status_code=201, summary="Analyze an uploaded ZIP archive of a Python repository")
def upload_archive(services: Services, file: UploadFile = File(..., description="ZIP archive of a Python project")) -> dict[str, Any]:
    return services.analyze_zip(file.file, file.filename or "")


@router.post("/github", status_code=201, summary="Clone and analyze a public GitHub repository")
def analyze_github(body: GitHubAnalysisRequest, services: Services) -> dict[str, Any]:
    return services.analyze_github(body.url)


@router.get("", summary="List analyses, newest first")
def list_analyses(services: Services, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return services.store.list_analyses(limit=limit)


@router.get("/{analysis_id}", summary="Analysis metadata and summary statistics")
def get_analysis(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    return services.store.get_analysis_meta(analysis_id)


@router.delete("/{analysis_id}", summary="Delete an analysis and its stored report")
def delete_analysis(analysis_id: AnalysisId, services: Services) -> dict[str, str]:
    services.delete_analysis(analysis_id)
    return {"deleted": analysis_id}


@router.get("/{analysis_id}/overview", summary="Dependency summary, cycles and warnings")
def overview(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    index = services.index(analysis_id)
    return index.summary() | {"unresolved_references": index.analysis["unresolved_references"][:50]}


@router.get("/{analysis_id}/files", summary="Python file tree with per-file statistics")
def list_files(analysis_id: AnalysisId, services: Services) -> list[dict[str, Any]]:
    return services.index(analysis_id).list_files()


@router.get("/{analysis_id}/file", summary="Details for one file: classes, functions, imports and findings")
def file_detail(analysis_id: AnalysisId, services: Services, path: str = Query(min_length=1, max_length=500)) -> dict[str, Any]:
    return services.index(analysis_id).file_detail(path)


@router.get("/{analysis_id}/source", summary="Raw source text of a Python file")
def file_source(analysis_id: AnalysisId, services: Services, path: str = Query(min_length=1, max_length=500)) -> dict[str, Any]:
    index = services.index(analysis_id)
    content = index.source_text(path)
    return {"path": path, "content": content, "lines": content.count("\n") + 1}


@router.get("/{analysis_id}/text-search", summary="Exact text search across every Python file")
def text_search(analysis_id: AnalysisId, services: Services,
                q: str = Query(min_length=1, max_length=200), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return {"query": q, "results": services.index(analysis_id).text_search(q, limit)}


@router.get("/{analysis_id}/import-search", summary="Find import statements that mention a module or name")
def import_search(analysis_id: AnalysisId, services: Services,
                  q: str = Query(min_length=1, max_length=200), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return {"query": q, "results": services.index(analysis_id).import_search(q, limit)}


@router.get("/{analysis_id}/symbols", summary="Search functions, methods and classes")
def list_symbols(analysis_id: AnalysisId, services: Services,
                 q: str | None = Query(None, max_length=200), file: str | None = Query(None, max_length=500),
                 kind: Literal["function", "method", "nested_function", "class"] | None = None,
                 limit: int = Query(200, ge=1, le=1000)) -> list[dict[str, Any]]:
    return services.index(analysis_id).list_symbols(q, file, kind, limit)


@router.get("/{analysis_id}/symbols/{symbol_id:path}", summary="Function or class details with callers and callees")
def symbol_detail(analysis_id: AnalysisId, symbol_id: str, services: Services) -> dict[str, Any]:
    return services.index(analysis_id).symbol_detail(symbol_id)


@router.get("/{analysis_id}/dependencies", summary="Dependency graph for React Flow (modules or functions)")
def dependency_graph(analysis_id: AnalysisId, services: Services,
                     scope: Literal["modules", "functions"] = "modules",
                     confidence: Literal["confirmed", "all"] = "confirmed",
                     max_nodes: int = Query(150, ge=10, le=500),
                     focus: str | None = Query(None, max_length=800),
                     q: str | None = Query(None, max_length=200),
                     module: str | None = Query(None, max_length=300)) -> dict[str, Any]:
    return services.index(analysis_id).dependency_graph(scope, confidence, max_nodes, focus, q, module)


@router.get("/{analysis_id}/dependencies/summary", summary="Dependency counts, hubs, cycles and unresolved references")
def dependency_summary(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    index = services.index(analysis_id)
    return {"summary": index.analysis["dependency_summary"], "cycles": index.cycles,
            "unresolved_references": index.analysis["unresolved_references"]}


@router.get("/{analysis_id}/modules/{module}/dependencies", summary="Imports and importers for one module")
def module_dependencies(analysis_id: AnalysisId, module: str, services: Services) -> dict[str, Any]:
    index = services.index(analysis_id)
    if module not in index.module_to_file:
        raise NotFoundError("Module not found in this analysis.")
    return index.dependency_summary_for_module(module)


@router.get("/{analysis_id}/call-flow", summary="Static call flow starting from a function")
def call_flow(analysis_id: AnalysisId, services: Services,
              symbol_id: str = Query(min_length=1, max_length=800), depth: int = Query(2, ge=1, le=4)) -> dict[str, Any]:
    return services.index(analysis_id).call_flow(symbol_id, depth=depth)


@router.get("/{analysis_id}/risks", summary="Risk findings with severity, rule and location filters")
def list_risks(analysis_id: AnalysisId, services: Services,
               min_severity: SeverityFilter = "info", category: str | None = Query(None, max_length=60),
               rule_id: str | None = Query(None, max_length=20), file: str | None = Query(None, max_length=500)) -> dict[str, Any]:
    index = services.index(analysis_id)
    findings = index.risks(min_severity, category, rule_id, file)
    from ..risks import summarize_findings

    return {"total": len(findings), "summary": summarize_findings(findings), "findings": findings}


@router.get("/{analysis_id}/risks/{finding_id}", summary="One finding with its source context")
def get_risk(analysis_id: AnalysisId, finding_id: str, services: Services) -> dict[str, Any]:
    index = services.index(analysis_id)
    finding = index.finding(finding_id)
    lines = index.files[finding["file"]]["content"].splitlines()
    start = max(1, finding["line"] - 4)
    end = min(len(lines), finding["line"] + 4)
    context = [{"line": n, "text": lines[n - 1]} for n in range(start, end + 1)]
    return {**finding, "context": context}


@router.get("/{analysis_id}/search", summary="Retrieve relevant source chunks for a query")
def search(analysis_id: AnalysisId, services: Services,
           q: str = Query(min_length=1, max_length=500), limit: int = Query(8, ge=1, le=25)) -> dict[str, Any]:
    return services.search(analysis_id, q, limit)


@router.post("/{analysis_id}/ask", summary="Ask a question grounded in repository source")
def ask(analysis_id: AnalysisId, body: AskRequest, services: Services) -> dict[str, Any]:
    return services.ask(analysis_id, body.question)


@router.post("/{analysis_id}/explain/file", summary="AI or deterministic explanation of one file")
def explain_file(analysis_id: AnalysisId, body: FileExplainRequest, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "file", body.path) | {"path": body.path}


@router.post("/{analysis_id}/explain/symbol", summary="AI or deterministic explanation of a function or class")
def explain_symbol(analysis_id: AnalysisId, body: SymbolExplainRequest, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "symbol", body.symbol_id)


@router.post("/{analysis_id}/explain/architecture", summary="Architecture summary of the repository")
def explain_architecture(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "architecture")


@router.post("/{analysis_id}/explain/module", summary="Explain a module's dependencies")
def explain_module(analysis_id: AnalysisId, body: ModuleExplainRequest, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "module", body.module)


@router.post("/{analysis_id}/explain/finding", summary="Explain a risk finding")
def explain_finding(analysis_id: AnalysisId, body: FindingExplainRequest, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "finding", body.finding_id)


@router.post("/{analysis_id}/explain/flow", summary="Explain the code flow starting from a function")
def explain_flow(analysis_id: AnalysisId, body: FlowExplainRequest, services: Services) -> dict[str, Any]:
    return services.explain(analysis_id, "flow", (body.symbol_id, body.depth))


@router.post("/{analysis_id}/report", summary="Generate the JSON analysis report")
def create_report(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    path = services.report_path(analysis_id)
    return {"analysis_id": analysis_id, "file": path.name, "download_url": f"/api/analyses/{analysis_id}/report/download"}


@router.get("/{analysis_id}/report/download", summary="Download the JSON analysis report")
def download_report(analysis_id: AnalysisId, services: Services) -> FileResponse:
    path = services.report_path(analysis_id)
    return FileResponse(path, media_type="application/json", filename=f"repomind-{analysis_id}.json")
