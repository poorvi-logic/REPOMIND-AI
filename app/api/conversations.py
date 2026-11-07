from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..schemas import ConversationCreateRequest, ConversationMessageRequest
from ..services import AppServices
from .deps import ANALYSIS_ID_PATTERN, get_services

router = APIRouter(prefix="/api/analyses/{analysis_id}/conversations", tags=["Assistant"])
AnalysisId = Annotated[str, Path(pattern=ANALYSIS_ID_PATTERN, description="Analysis identifier")]
ConversationId = Annotated[str, Path(pattern=r"^[a-f0-9]{12}$", description="Conversation identifier")]
Services = Annotated[AppServices, Depends(get_services)]


@router.post("", status_code=201, summary="Start a conversation about a project")
def create_conversation(analysis_id: AnalysisId, services: Services, body: ConversationCreateRequest | None = None) -> dict[str, Any]:
    return services.create_conversation(analysis_id, body.title if body else None)


@router.get("", summary="List conversations for a project, newest first")
def list_conversations(analysis_id: AnalysisId, services: Services) -> list[dict[str, Any]]:
    return services.list_conversations(analysis_id)


@router.get("/{conversation_id}", summary="Conversation with its messages")
def get_conversation(analysis_id: AnalysisId, conversation_id: ConversationId, services: Services) -> dict[str, Any]:
    return services.conversation_detail(analysis_id, conversation_id)


@router.delete("/{conversation_id}", summary="Delete a conversation")
def delete_conversation(analysis_id: AnalysisId, conversation_id: ConversationId, services: Services) -> dict[str, str]:
    services.delete_conversation(analysis_id, conversation_id)
    return {"deleted": conversation_id}


@router.post("/{conversation_id}/messages", summary="Ask a question and wait for the full answer")
def send_message(analysis_id: AnalysisId, conversation_id: ConversationId, body: ConversationMessageRequest,
                 services: Services) -> dict[str, Any]:
    return services.send_message(analysis_id, conversation_id, body.question, body.mode)


@router.post("/{conversation_id}/stream", summary="Ask a question and receive the answer as it is written (NDJSON)")
def stream_message(analysis_id: AnalysisId, conversation_id: ConversationId, body: ConversationMessageRequest,
                   services: Services) -> StreamingResponse:
    events = services.stream_message(analysis_id, conversation_id, body.question, body.mode)

    def lines():
        for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
