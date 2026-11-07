from __future__ import annotations

import numpy as np

from app.retrieval import LexicalIndex, VectorIndex, build_chunks, reciprocal_rank_fusion, search_chunks, tokenize
from app.extractor import extract_structure, parse_source
from tests.fakes import bag_of_words_vector

SOURCE = (
    "import os\n\n"
    "def validate_payment(amount):\n"
    "    if amount <= 0:\n"
    "        return False\n"
    "    return True\n\n"
    "class Checkout:\n"
    "    def run(self):\n"
    "        return validate_payment(1)\n"
)


def _chunks_for(source: str, path: str = "shop/pay.py"):
    tree, error = parse_source(source, path)
    symbols = extract_structure(tree, path)["symbols"] if tree else []
    return build_chunks(path, source.splitlines(), symbols, error is None)


def test_identifiers_are_split_into_searchable_terms():
    tokens = tokenize("validate_payment validatePayment HTTPServer")
    assert {"validate", "payment", "validatepayment", "http", "server"} <= set(tokens)
    assert "the" not in tokenize("the payment")


def test_chunks_follow_functions_classes_and_methods():
    chunks = _chunks_for(SOURCE)
    by_symbol = {chunk["symbol"]: chunk for chunk in chunks if chunk["symbol"]}
    assert by_symbol["validate_payment"]["kind"] == "function"
    assert by_symbol["Checkout.run"]["kind"] == "method"
    assert by_symbol["Checkout.run"]["start_line"] == 9
    assert any(chunk["kind"] == "module" and chunk["start_line"] == 1 for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)


def test_unparseable_files_fall_back_to_line_windows():
    chunks = _chunks_for("def broken(:\n    pass\n", "bad.py")
    assert chunks and all(chunk["kind"] == "module" for chunk in chunks)


def test_lexical_search_ranks_the_matching_function_first():
    chunks = _chunks_for(SOURCE)
    index = LexicalIndex(chunks)
    hits = index.search("payment validation", limit=3)
    top = chunks[hits[0]["index"]]
    assert top["symbol"] == "validate_payment"
    assert "payment" in hits[0]["matched_terms"]


def test_symbol_name_match_outranks_body_only_match():
    chunks = _chunks_for(SOURCE)
    index = LexicalIndex(chunks)
    hits = index.search("checkout run", limit=2)
    assert chunks[hits[0]["index"]]["symbol"] == "Checkout.run"


def test_unrelated_query_returns_no_hits_for_insufficient_evidence_handling():
    index = LexicalIndex(_chunks_for(SOURCE))
    assert index.search("quantum blockchain zebra", limit=5) == []
    assert index.search("what is the", limit=5) == []


def test_search_result_contains_citation_fields():
    chunks = _chunks_for(SOURCE)
    hits = search_chunks(chunks, LexicalIndex(chunks), "validate payment", limit=2)
    first = hits[0]
    assert {"file", "line", "end_line", "symbol", "snippet", "score", "method"} <= set(first)
    assert first["method"] == "lexical"
    assert first["file"] == "shop/pay.py"


def test_hybrid_search_fuses_lexical_and_vector_rankings():
    chunks = _chunks_for(SOURCE)
    lexical = LexicalIndex(chunks)
    matrix = np.asarray([bag_of_words_vector(chunk["text"]) for chunk in chunks], dtype=np.float32)
    vectors = VectorIndex([chunk["id"] for chunk in chunks], matrix)
    query_vector = np.asarray(bag_of_words_vector("checkout run"), dtype=np.float32)
    hits = search_chunks(chunks, lexical, "checkout run", limit=3, vector_index=vectors, query_vector=query_vector)
    assert hits and all(hit["method"] == "hybrid" for hit in hits)
    assert hits[0]["symbol"] == "Checkout.run"


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], limit=4)
    order = [item[0] for item in fused]
    assert order[:2] == ["a", "b"] or order[:2] == ["b", "a"]
    assert set(order) == {"a", "b", "c", "d"}


def test_vector_search_respects_minimum_score_and_handles_zero_vectors():
    vectors = VectorIndex(["x", "y"], np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    assert vectors.search(np.asarray([0.0, 0.0], dtype=np.float32)) == []
    results = vectors.search(np.asarray([1.0, 0.0], dtype=np.float32))
    assert results[0][0] == "x"
