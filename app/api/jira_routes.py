from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..errors import InputError
from ..schemas import JiraConnectionRequest, JiraCreateRequest, JiraTicketRequest
from ..services import AppServices
from .deps import get_services

router = APIRouter(prefix="/api/jira", tags=["Jira"])
Services = Annotated[AppServices, Depends(get_services)]


@router.get("/status", summary="Jira connection status (never returns the API token)")
def status(services: Services) -> dict[str, Any]:
    return services.jira.public_status()


@router.post("/connection", summary="Connect a Jira Cloud site for this server session")
def connect(body: JiraConnectionRequest, services: Services) -> dict[str, Any]:
    return services.connect_jira(body.site_url, body.email, body.api_token)


@router.delete("/connection", summary="Remove the session credentials entered in the UI")
def disconnect(services: Services) -> dict[str, Any]:
    return services.disconnect_jira()


@router.get("/projects", summary="Projects and issue types available to the connected account")
def projects(services: Services) -> list[dict[str, Any]]:
    return services.jira_projects()


@router.post("/tickets/preview", summary="Preview the Jira issue built from a finding (nothing is created)")
def preview(body: JiraTicketRequest, services: Services) -> dict[str, Any]:
    return services.jira_preview(body.analysis_id, body.finding_id, body.project_key, body.issue_type)


@router.post("/tickets", status_code=201, summary="Create the Jira issue after explicit confirmation")
def create(body: JiraCreateRequest, services: Services) -> dict[str, Any]:
    if not body.confirm:
        raise InputError("Set confirm to true to create this issue in Jira.")
    return services.jira_create(body.analysis_id, body.finding_id, body.project_key, body.issue_type)


@router.get("/tickets", summary="Issues created through RepoMind")
def list_tickets(services: Services, limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
    return services.store.list_jira_tickets(limit=limit)


@router.get("/issues/{issue_key}/status", summary="Live status of a Jira issue")
def issue_status(issue_key: str, services: Services) -> dict[str, Any]:
    return services.jira_issue_status(issue_key)
