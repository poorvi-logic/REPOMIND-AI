from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.analyses import router as analyses_router
from .api.conversations import router as conversations_router
from .api.learning import router as learning_router
from .api.jira_routes import router as jira_router
from .api.legacy import router as legacy_router
from .api.system import router as system_router
from .config import Settings, load_settings
from .errors import RepoMindError
from .services import AppServices

DESCRIPTION = (
    "RepoMind AI analyses Python repositories with AST extraction, static dependency intelligence, risk review, "
    "source-grounded question answering, optional OpenAI explanations, Jira ticket creation and MCP tools. "
    "Relationships are labelled confirmed, approximate, external or unresolved. Risk findings are heuristic."
)
FALLBACK_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>RepoMind AI</title></head>
<body style="font-family:system-ui;background:#0b1120;color:#e5e9f5;padding:40px">
<h1>RepoMind AI</h1><p>The interface is not built yet. Run <b>npm run build</b> in the frontend folder.</p>
<p><a style="color:#9aa8ff" href="/docs">API documentation</a></p></body></html>"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    services = AppServices(settings)
    app = FastAPI(title="RepoMind AI", version=__version__, description=DESCRIPTION)
    app.state.settings = settings
    app.state.services = services

    @app.exception_handler(RepoMindError)
    def handle_repomind_error(_, exc: RepoMindError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    app.include_router(system_router)
    app.include_router(analyses_router)
    app.include_router(conversations_router)
    app.include_router(learning_router)
    app.include_router(jira_router)
    app.include_router(legacy_router)
    _mount_frontend(app, settings.frontend_dist_dir)
    return app


def _mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist_dir / full_path).resolve() if full_path else dist_dir / "index.html"
        if dist_dir.exists() and candidate.is_file() and dist_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        index_file = dist_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse(FALLBACK_HTML)


_app: FastAPI | None = None


def __getattr__(name: str):
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
