from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GitHubAnalysisRequest(BaseModel):
    url: str = Field(min_length=1, max_length=300, description="Public GitHub repository URL, e.g. https://github.com/psf/requests")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class FileExplainRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class SymbolExplainRequest(BaseModel):
    symbol_id: str = Field(min_length=1, max_length=800)


class ModuleExplainRequest(BaseModel):
    module: str = Field(min_length=1, max_length=300)


class FindingExplainRequest(BaseModel):
    finding_id: str = Field(min_length=1, max_length=120)


class FlowExplainRequest(BaseModel):
    symbol_id: str = Field(min_length=1, max_length=800)
    depth: int = Field(default=2, ge=1, le=4)


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_risk_severity: Literal["high", "medium", "low", "info"] | None = None
    graph_max_nodes: int | None = Field(default=None, ge=20, le=500)
    retrieval_mode: Literal["lexical", "hybrid"] | None = None
    show_approximate_edges: bool | None = None


class JiraConnectionRequest(BaseModel):
    site_url: str = Field(min_length=8, max_length=200, examples=["https://your-team.atlassian.net"])
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    api_token: str = Field(min_length=8, max_length=500, repr=False)


class JiraTicketRequest(BaseModel):
    analysis_id: str = Field(min_length=12, max_length=12)
    finding_id: str = Field(min_length=1, max_length=120)
    project_key: str = Field(min_length=2, max_length=10)
    issue_type: str = Field(default="Task", min_length=1, max_length=40)


class JiraCreateRequest(JiraTicketRequest):
    confirm: bool = Field(description="Must be true to create the issue in Jira.")


class AIConnectionRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=300, repr=False)


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)


class ConversationMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["beginner", "developer", "deep_dive"] = "developer"


class LearningGenerateRequest(BaseModel):
    mode: Literal["mixed", "architecture", "function", "workflow", "bug", "dependency", "risk"] = "mixed"
    difficulty: Literal["beginner", "intermediate", "advanced"] | None = None
    module: str | None = Field(default=None, max_length=300)
    count: int = Field(default=5, ge=1, le=10)


class LearningAnswerRequest(BaseModel):
    selected: list[str] | None = Field(default=None, max_length=10)
    order: list[str] | None = Field(default=None, max_length=10)
