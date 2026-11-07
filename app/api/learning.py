from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from ..schemas import LearningAnswerRequest, LearningGenerateRequest
from ..services import AppServices
from .deps import ANALYSIS_ID_PATTERN, get_services

router = APIRouter(prefix="/api/analyses/{analysis_id}/learning", tags=["CodeQuest"])
AnalysisId = Annotated[str, Path(pattern=ANALYSIS_ID_PATTERN, description="Analysis identifier")]
QuestionId = Annotated[str, Path(pattern=r"^[a-f0-9]{12}$", description="Question identifier")]
Services = Annotated[AppServices, Depends(get_services)]


@router.get("/overview", summary="Practice modes, modules and progress for a repository")
def learning_overview(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    return services.learning_overview(analysis_id)


@router.post("/questions", summary="Build practice questions from this repository's analysis")
def generate_questions(analysis_id: AnalysisId, body: LearningGenerateRequest, services: Services) -> dict[str, Any]:
    return services.learning_generate(analysis_id, body.mode, body.difficulty, body.module, body.count)


@router.post("/questions/{question_id}/hint", summary="Reveal a hint (answers given after a hint earn half points)")
def question_hint(analysis_id: AnalysisId, question_id: QuestionId, services: Services) -> dict[str, Any]:
    return services.learning_hint(analysis_id, question_id)


@router.post("/questions/{question_id}/answer", summary="Check an answer against the stored answer key")
def answer_question(analysis_id: AnalysisId, question_id: QuestionId, body: LearningAnswerRequest, services: Services) -> dict[str, Any]:
    return services.learning_answer(analysis_id, question_id, body.selected, body.order)


@router.get("/progress", summary="Score, accuracy and the review list for this repository")
def learning_progress(analysis_id: AnalysisId, services: Services) -> dict[str, Any]:
    return services.learning_progress(analysis_id)
