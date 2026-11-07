from __future__ import annotations

from fastapi import Request

from ..services import AppServices

ANALYSIS_ID_PATTERN = r"^[a-f0-9]{12}$"


def get_services(request: Request) -> AppServices:
    return request.app.state.services
