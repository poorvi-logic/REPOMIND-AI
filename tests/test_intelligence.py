from __future__ import annotations

import httpx
import openai
import pytest

from app.index import RepositoryIndex
from app.ingestion import IngestionLimits
from app.intelligence import (
    AnalysisCache, answer_question, explain_architecture, explain_file, explain_finding, explain_flow,
    explain_module_dependencies, explain_symbol,
)
from app.llm import LLMClient, classify_error
from app.pipeline import analyze_directory
from app.store import Store
from tests.fakes import FakeLLM, make_fake_client


@pytest.fixture(scope="module")
def index(sample_dir):
    return RepositoryIndex(analyze_directory(sample_dir, analysis_id="intelindex01", repository_name="sample",
                                             source_type="local", source_ref="sample", limits=IngestionLimits()))


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _error_for(kind: str) -> Exception:
    request = _request()
    if kind == "rate":
        return openai.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)
    if kind == "auth":
        return openai.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    if kind == "timeout":
        return openai.APITimeoutError(request=request)
    return openai.APIStatusError("server error", response=httpx.Response(500, request=request), body=None)


@pytest.mark.parametrize("kind, status", [
    ("rate", "rate_limited"), ("auth", "auth_error"), ("timeout", "timeout"), ("server", "api_error"),
])
def test_openai_errors_are_classified(kind, status):
    assert classify_error(_error_for(kind)) == status


def test_llm_client_maps_rate_limit_without_raising():
    client = LLMClient("key", "gpt-test", "embed-test", 5,
                       client_factory=lambda: make_fake_client(create_exception=_error_for("rate")))
    result = client.complete("system", "user")
    assert result.status == "rate_limited"
    assert result.text is None


def test_llm_client_returns_text_on_success_and_flags_empty_replies():
    ok = LLMClient("key", "gpt-test", "embed-test", 5, client_factory=lambda: make_fake_client(reply="hello"))
    assert ok.complete("s", "u").text == "hello"
    empty = LLMClient("key", "gpt-test", "embed-test", 5, client_factory=lambda: make_fake_client(reply="   "))
    assert empty.complete("s", "u").status == "empty_response"


def test_llm_embeddings_validate_vector_count():
    client = LLMClient("key", "gpt-test", "embed-test", 5, client_factory=lambda: make_fake_client())
    status, vectors = client.embed(["one", "two"])
    assert status == "ok" and len(vectors) == 2
    failing = LLMClient("key", "gpt-test", "embed-test", 5,
                        client_factory=lambda: make_fake_client(create_exception=_error_for("timeout")))
    assert failing.embed(["x"]) == ("timeout", None)


def test_disabled_llm_returns_deterministic_explanations(index):
    llm = FakeLLM(enabled=False)
    result = explain_file(index, "payment.py", llm)
    assert result["mode"] == "deterministic"
    assert result["ai_status"] == "disabled"
    assert "validate_payment" in result["text"]
    assert llm.calls == []


def test_symbol_explanation_lists_confirmed_and_approximate_links(index):
    result = explain_symbol(index, "main.py::checkout", FakeLLM(enabled=False))
    assert "Exact calls" in result["text"]
    assert "validate_payment" in result["text"]
    approximate = explain_symbol(index, "api.py::refund_order", FakeLLM(enabled=False))
    assert "Name-based calls" in approximate["text"]


def test_llm_success_is_used_and_cached(index, tmp_path):
    store = Store(tmp_path / "cache.db")
    store.save_analysis(_stored_analysis(index))
    cache = AnalysisCache(store, index.analysis_id, "fake-model")
    llm = FakeLLM(reply="The function validates the payment amount.")
    first = explain_symbol(index, "payment.py::validate_payment", llm, cache)
    second = explain_symbol(index, "payment.py::validate_payment", llm, cache)
    assert first["mode"] == "llm" and first["ai_status"] == "ok"
    assert first["text"] == "The function validates the payment amount."
    assert second["cached"] is True
    assert len(llm.calls) == 1
    store.close()


def _stored_analysis(index: RepositoryIndex) -> dict:
    return dict(index.analysis)


def test_llm_error_falls_back_to_deterministic_text_with_status(index):
    result = explain_symbol(index, "payment.py::validate_payment", FakeLLM(status="rate_limited"))
    assert result["mode"] == "deterministic"
    assert result["ai_status"] == "rate_limited"
    assert "AI explanation unavailable (rate_limited)" in result["text"]


def test_architecture_summary_uses_static_facts(index):
    result = explain_architecture(index, FakeLLM(enabled=False))
    assert "internal module dependencies" in result["text"]
    assert "Import cycles" in result["text"]
    assert "orders" in result["text"]


def test_module_dependency_explanation_and_unknown_module(index):
    result = explain_module_dependencies(index, "orders", FakeLLM(enabled=False))
    assert "orders" in result["text"]
    assert "import cycle" in result["text"]
    with pytest.raises(Exception):
        explain_module_dependencies(index, "not_a_module", FakeLLM(enabled=False))


def test_finding_explanation_keeps_heuristic_wording(index):
    finding_id = next(item["id"] for item in index.findings.values() if item["rule_id"] == "RM-SEC-002")
    result = explain_finding(index, finding_id, FakeLLM(enabled=False))
    assert "heuristic" in result["text"].lower() or "review" in result["text"].lower()
    assert "Suggested remediation" in result["text"]


def test_flow_explanation_contains_the_static_call_tree(index):
    result = explain_flow(index, "main.py::main", 3, FakeLLM(enabled=False))
    assert "checkout" in result["text"]
    assert result["references"][0]["symbol_id"] == "main.py::main"


def test_question_without_matching_evidence_never_calls_the_model(index):
    llm = FakeLLM()
    result = answer_question(index, "zebra quantum banana", [], llm, "lexical")
    assert result["insufficient_evidence"] is True
    assert result["mode"] == "insufficient-evidence"
    assert llm.calls == []


def test_question_without_llm_lists_grounded_excerpts(index):
    hits = index.search("payment validation", limit=3)
    result = answer_question(index, "Where is payment validation?", hits, FakeLLM(enabled=False), "lexical")
    assert result["mode"] == "deterministic"
    assert "[S1] payment.py" in result["answer"]
    assert result["references"][0]["file"] == "payment.py"


def test_llm_answer_citations_are_parsed_and_validated(index):
    hits = index.search("payment validation", limit=3)
    llm = FakeLLM(reply="Payment is validated by validate_payment [S1] which checks the amount [S9].")
    result = answer_question(index, "Where is payment validation?", hits, llm, "lexical")
    assert result["mode"] == "llm"
    assert [c["file"] for c in result["citations"]] == ["payment.py"]
    assert result["uncited"] is False
    assert "[S1] payment.py" in llm.calls[0][1]


def test_uncited_llm_answer_is_flagged(index):
    hits = index.search("payment validation", limit=3)
    result = answer_question(index, "Where is payment validation?", hits,
                             FakeLLM(reply="It is validated somewhere."), "lexical")
    assert result["uncited"] is True
    assert result["citations"] == []


def test_model_reported_insufficient_evidence_is_respected(index):
    hits = index.search("payment validation", limit=3)
    result = answer_question(index, "Where is payment validation?", hits,
                             FakeLLM(reply="INSUFFICIENT_EVIDENCE The excerpts only mention payments."), "lexical")
    assert result["insufficient_evidence"] is True
    assert result["answer"].startswith("The excerpts")


def test_llm_failure_during_qa_falls_back_to_excerpts(index):
    hits = index.search("payment validation", limit=3)
    result = answer_question(index, "Where is payment validation?", hits, FakeLLM(status="timeout"), "lexical")
    assert result["mode"] == "deterministic"
    assert result["ai_status"] == "timeout"
