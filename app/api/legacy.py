from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..errors import InputError, NotFoundError
from ..schemas import AskRequest
from ..services import AppServices
from ..tickets import make_ticket_draft
from .deps import get_services

router = APIRouter(tags=["Legacy"])
Services = Annotated[AppServices, Depends(get_services)]


class TicketDraftRequest(BaseModel):
    finding_index: int = Field(ge=0)


def _latest_analysis_id(services: AppServices) -> str:
    latest = services.store.list_analyses(limit=1)
    if not latest:
        raise NotFoundError("No repository has been analyzed yet.")
    return latest[0]["analysis_id"]


@router.post("/api/analyze/upload", status_code=201, summary="Legacy: upload a ZIP archive")
def legacy_upload(services: Services, file: UploadFile = File(...)) -> dict[str, Any]:
    meta = services.analyze_zip(file.file, file.filename or "")
    return _legacy_report(services, meta["analysis_id"])


@router.get("/api/report/latest", summary="Legacy: latest analysis report")
def legacy_latest(services: Services) -> dict[str, Any]:
    return _legacy_report(services, _latest_analysis_id(services))


@router.get("/api/report/download", summary="Legacy: download the latest JSON report")
def legacy_download(services: Services) -> FileResponse:
    path = services.report_path(_latest_analysis_id(services))
    return FileResponse(path, media_type="application/json", filename="repomind-analysis.json")


@router.get("/api/search", summary="Legacy: search the latest analysis")
def legacy_search(services: Services, q: str = Query(min_length=1, max_length=500)) -> dict[str, Any]:
    result = services.search(_latest_analysis_id(services), q, limit=8)
    return {"query": q, "results": result["results"]}


@router.post("/api/ask", summary="Legacy: ask about the latest analysis")
def legacy_ask(body: AskRequest, services: Services) -> dict[str, Any]:
    return services.ask(_latest_analysis_id(services), body.question)


@router.get("/api/explain/{file_path:path}", summary="Legacy: explain a file in the latest analysis")
def legacy_explain(file_path: str, services: Services) -> dict[str, Any]:
    result = services.explain(_latest_analysis_id(services), "file", file_path)
    return {"file": file_path, "explanation": result["text"]}


@router.post("/api/ticket-draft", summary="Legacy: Jira-style draft from a finding index")
def legacy_ticket(body: TicketDraftRequest, services: Services) -> dict[str, Any]:
    analysis_id = _latest_analysis_id(services)
    index = services.index(analysis_id)
    findings = list(index.findings.values())
    if body.finding_index >= len(findings):
        raise NotFoundError("Finding index not found.")
    finding = findings[body.finding_index]
    return make_ticket_draft(finding, index.analysis["repository"], analysis_id)


def _legacy_report(services: AppServices, analysis_id: str) -> dict[str, Any]:
    index = services.index(analysis_id)
    return {
        "analysis_id": analysis_id,
        "repository": index.analysis["repository"],
        "summary": index.analysis["summary"],
        "findings": index.analysis["findings"],
        "function_relationships": [edge for edge in index.call_edges if edge["target"]][:500],
        "files": index.list_files(),
    }
