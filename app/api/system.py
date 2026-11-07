from __future__ import annotations

import sys
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..config import BASE_DIR
from ..mcp_tools import tool_catalog
from ..schemas import AIConnectionRequest, PreferencesUpdate
from ..services import AppServices
from .deps import get_services

router = APIRouter(prefix="/api", tags=["System"])
Services = Annotated[AppServices, Depends(get_services)]


@router.get("/health", summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok", "project": "RepoMind AI"}


@router.get("/meta/config", summary="Non-secret runtime configuration")
def runtime_config(services: Services) -> dict[str, Any]:
    settings = services.settings
    return {
        "version": "2.0.0",
        "ai_enabled": services.llm.enabled,
        "model": services.llm.model,
        "embedding_model": services.llm.embedding_model,
        "retrieval_mode": services.retrieval_method,
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_repository_mb": settings.max_repository_mb,
            "max_python_files": settings.max_python_files,
            "max_file_kb": settings.max_file_kb,
            "clone_timeout_seconds": settings.clone_timeout_seconds,
        },
        "jira": services.jira.public_status(),
        "mcp_tool_count": len(tool_catalog()),
    }


@router.get("/settings", summary="Application preferences (no secrets are stored here)")
def get_settings(services: Services) -> dict[str, Any]:
    return services.preferences()


@router.put("/settings", summary="Update application preferences")
def update_settings(body: PreferencesUpdate, services: Services) -> dict[str, Any]:
    values = {key: value for key, value in body.model_dump().items() if value is not None}
    return services.update_preferences(values)


@router.get("/ai/status", summary="Whether an OpenAI key is connected (the key itself is never returned)")
def ai_status(services: Services) -> dict[str, Any]:
    return services.ai_status()


@router.post("/ai/connection", summary="Validate and connect an OpenAI API key for this server session")
def ai_connect(body: AIConnectionRequest, services: Services) -> dict[str, Any]:
    return services.connect_ai(body.api_key)


@router.delete("/ai/connection", summary="Remove the session key entered in the UI")
def ai_disconnect(services: Services) -> dict[str, Any]:
    return services.disconnect_ai()


@router.get("/mcp/tools", summary="MCP tools exposed by the RepoMind server")
def mcp_tools() -> list[dict[str, Any]]:
    return tool_catalog()


@router.get("/mcp/status", summary="Whether the MCP server loads and registers every tool")
def mcp_status() -> dict[str, Any]:
    import asyncio

    from ..mcp_server import mcp

    expected = sorted(item["name"] for item in tool_catalog())
    registered = sorted(tool.name for tool in asyncio.run(mcp.list_tools()))
    return {
        "ready": registered == expected,
        "tools_registered": len(registered),
        "tools_expected": len(expected),
        "missing": sorted(set(expected) - set(registered)),
        "launch_command": [sys.executable, "-m", "app.mcp_server"],
    }


@router.get("/mcp/config", summary="Example MCP client configuration for this installation")
def mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "repomind-ai": {
                "command": sys.executable,
                "args": ["-m", "app.mcp_server"],
                "cwd": str(BASE_DIR),
            }
        }
    }
