from __future__ import annotations

import hashlib
from typing import Any

from app.llm import LLMResult


class FakeLLM:
    model = "fake-model"
    embedding_model = "fake-embedding"

    def __init__(self, reply: str = "Fake explanation grounded in the supplied facts.", status: str = "ok",
                 enabled: bool = True) -> None:
        self.reply = reply
        self.status = status
        self._enabled = enabled
        self.calls: list[tuple[str, str]] = []
        self.embed_calls = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def complete(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900) -> LLMResult:
        self.calls.append((system_prompt, user_prompt))
        if self.status != "ok":
            return LLMResult(self.status, None, self.model)
        return LLMResult("ok", self.reply, self.model)

    def stream(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900):
        self.calls.append((system_prompt, user_prompt))
        if self.status != "ok":
            raise RuntimeError("upstream failure")
        for piece in self.reply.split(" "):
            yield piece + " "

    def embed(self, texts: list[str]) -> tuple[str, list[list[float]] | None]:
        self.embed_calls += 1
        return "ok", [bag_of_words_vector(text) for text in texts]


def bag_of_words_vector(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split():
        bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dimensions
        vector[bucket] += 1.0
    return vector


def make_fake_client(create_exception: Exception | None = None, reply: str = "ok reply") -> Any:
    class _Message:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = _Message(content)

    class _Completion:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            if create_exception is not None:
                raise create_exception
            return _Completion(reply)

    class _Chat:
        completions = _Completions()

    class _Embeddings:
        def create(self, model: str, input: list[str]) -> Any:
            class _Item:
                def __init__(self, index: int, embedding: list[float]) -> None:
                    self.index = index
                    self.embedding = embedding

            class _Response:
                data = [_Item(i, bag_of_words_vector(text)) for i, text in enumerate(input)]

            if create_exception is not None:
                raise create_exception
            return _Response()

    class _Client:
        chat = _Chat()
        embeddings = _Embeddings()

    return _Client()
