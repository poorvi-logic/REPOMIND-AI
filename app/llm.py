from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import openai
from openai import OpenAI

MAX_PROMPT_CHARS = 24000


@dataclass(frozen=True)
class LLMResult:
    status: str
    text: str | None
    model: str | None


def classify_error(exc: Exception) -> str:
    if isinstance(exc, openai.AuthenticationError):
        return "auth_error"
    if isinstance(exc, openai.RateLimitError):
        return "rate_limited"
    if isinstance(exc, openai.APITimeoutError):
        return "timeout"
    return "api_error"


class LLMClient:
    def __init__(self, api_key: str, model: str, embedding_model: str, timeout_seconds: int,
                 client_factory: Callable[[], Any] | None = None) -> None:
        self._environment_key = api_key
        self._session_key = ""
        self.model = model
        self.embedding_model = embedding_model
        self._timeout = timeout_seconds
        self._client_factory = client_factory
        self._client: Any = None

    @property
    def key_source(self) -> str | None:
        if self._session_key:
            return "session"
        if self._environment_key:
            return "environment"
        return None

    @property
    def enabled(self) -> bool:
        return self.key_source is not None or self._client_factory is not None

    def connect(self, api_key: str) -> None:
        self._session_key = api_key
        self._client = None

    def disconnect(self) -> None:
        self._session_key = ""
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                active_key = self._session_key or self._environment_key
                self._client = OpenAI(api_key=active_key, timeout=self._timeout, max_retries=2)
        return self._client

    def check_key(self) -> str:
        if not self.enabled:
            return "disabled"
        try:
            self._get_client().models.list()
        except Exception as exc:
            return classify_error(exc)
        return "ok"

    def complete(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900) -> LLMResult:
        if not self.enabled:
            return LLMResult("disabled", None, None)
        try:
            response = self._get_client().chat.completions.create(
                model=self.model,
                temperature=0.1,
                max_completion_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt[:MAX_PROMPT_CHARS]},
                ],
            )
        except Exception as exc:
            return LLMResult(classify_error(exc), None, self.model)
        text = (response.choices[0].message.content or "").strip() if response.choices else ""
        if not text:
            return LLMResult("empty_response", None, self.model)
        return LLMResult("ok", text, self.model)

    def stream(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900) -> Any:
        completions = self._get_client().chat.completions.create(
            model=self.model,
            temperature=0.1,
            max_completion_tokens=max_output_tokens,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:MAX_PROMPT_CHARS]},
            ],
        )
        for chunk in completions:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def embed(self, texts: list[str]) -> tuple[str, list[list[float]] | None]:
        if not self.enabled:
            return "disabled", None
        try:
            response = self._get_client().embeddings.create(model=self.embedding_model, input=texts)
        except Exception as exc:
            return classify_error(exc), None
        vectors = [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts):
            return "api_error", None
        return "ok", vectors
