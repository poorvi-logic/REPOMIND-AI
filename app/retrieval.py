from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

import numpy as np

MAX_UNIT_LINES = 120
WINDOW_LINES = 60
SNIPPET_LINES = 40
RRF_K = 60
EMBEDDING_MIN_SCORE = 0.2
K1 = 1.4
B = 0.75
SYMBOL_BOOST = 2.0
PATH_BOOST = 0.8

STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could", "did", "do", "does",
    "for", "from", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "no", "not", "of", "on",
    "or", "our", "that", "the", "their", "them", "then", "there", "these", "this", "to", "was", "we", "what",
    "when", "where", "which", "who", "why", "will", "with", "you", "your", "self", "cls", "none", "true",
    "false", "def", "class", "return", "import", "pass", "lambda", "while", "else", "elif", "try", "except",
    "finally", "raise", "yield", "async", "await", "global", "nonlocal", "does", "happen", "happens",
    "about", "show", "find", "implemented", "implementation", "use", "used", "using", "called", "call",
})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _keep(token: str) -> bool:
    return len(token) > 1 and token not in STOPWORDS


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for identifier in _IDENTIFIER.findall(text or ""):
        lowered = identifier.lower()
        if _keep(lowered):
            tokens.append(lowered)
        if "_" in identifier or any(character.isupper() for character in identifier[1:]):
            for segment in identifier.split("_"):
                for part in _CAMEL_PART.findall(segment):
                    lowered_part = part.lower()
                    if _keep(lowered_part):
                        tokens.append(lowered_part)
    return tokens


def _window(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    spans = []
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + WINDOW_LINES - 1)
        spans.append((cursor, window_end))
        cursor = window_end + 1
    return spans


def _make_chunk(relative_path: str, lines: list[str], start: int, end: int, symbol: dict[str, Any] | None,
                kind: str) -> dict[str, Any] | None:
    text = "\n".join(lines[start - 1:end])
    if not text.strip():
        return None
    return {
        "id": f"{relative_path}#L{start}-L{end}",
        "file": relative_path,
        "start_line": start,
        "end_line": end,
        "symbol_id": symbol["id"] if symbol else None,
        "symbol": symbol["qualname"] if symbol else None,
        "kind": kind,
        "text": text,
    }


def build_chunks(relative_path: str, lines: list[str], symbols: list[dict[str, Any]], parse_ok: bool) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    covered: set[int] = set()
    if parse_ok:
        file_symbols = [item for item in symbols if item["file"] == relative_path]
        for symbol in file_symbols:
            if symbol["is_nested"]:
                continue
            if symbol["kind"] == "class":
                member_starts = [m["start_line"] for m in file_symbols
                                 if m["class_name"] == symbol["qualname"] and m["kind"] == "method"]
                header_end = min(member_starts) - 1 if member_starts else symbol["end_line"]
                spans = [(symbol["start_line"], header_end)] if header_end >= symbol["start_line"] else []
                kind = "class"
            elif symbol["kind"] in {"function", "method"}:
                spans = [(symbol["start_line"], symbol["end_line"])]
                kind = symbol["kind"]
            else:
                continue
            for start, end in spans:
                pieces = [(start, end)] if end - start + 1 <= MAX_UNIT_LINES else _window(lines, start, end)
                for piece_start, piece_end in pieces:
                    chunk = _make_chunk(relative_path, lines, piece_start, piece_end, symbol, kind)
                    if chunk:
                        chunks.append(chunk)
                        covered.update(range(piece_start, piece_end + 1))
    gap_start = None
    for line_number in range(1, len(lines) + 2):
        is_gap = line_number <= len(lines) and line_number not in covered
        if is_gap and gap_start is None:
            gap_start = line_number
        elif not is_gap and gap_start is not None:
            for start, end in _window(lines, gap_start, line_number - 1):
                chunk = _make_chunk(relative_path, lines, start, end, None, "module")
                if chunk:
                    chunks.append(chunk)
            gap_start = None
    return sorted(chunks, key=lambda item: (item["start_line"], item["end_line"]))


class LexicalIndex:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_lengths: list[int] = []
        self.symbol_tokens: list[set[str]] = []
        self.path_tokens: list[set[str]] = []
        for doc_index, chunk in enumerate(chunks):
            tokens = tokenize(chunk["text"])
            self.doc_lengths.append(len(tokens))
            for term, frequency in Counter(tokens).items():
                self.postings[term].append((doc_index, frequency))
            self.symbol_tokens.append(set(tokenize(chunk.get("symbol") or "")))
            self.path_tokens.append(set(tokenize(chunk["file"])))
        self.average_length = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_lengths else 0.0

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        query_terms = list(dict.fromkeys(tokenize(query)))
        if not query_terms or not self.chunks:
            return []
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        document_count = len(self.chunks)
        for term in query_terms:
            postings = self.postings.get(term)
            if not postings:
                continue
            document_frequency = len(postings)
            idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
            for doc_index, frequency in postings:
                length_norm = 1 - B + B * self.doc_lengths[doc_index] / max(self.average_length, 1.0)
                scores[doc_index] += idf * (frequency * (K1 + 1)) / (frequency + K1 * length_norm)
                matched[doc_index].add(term)
        for doc_index in list(scores):
            for term in query_terms:
                if term in self.symbol_tokens[doc_index]:
                    scores[doc_index] += SYMBOL_BOOST
                    matched[doc_index].add(term)
                elif term in self.path_tokens[doc_index]:
                    scores[doc_index] += PATH_BOOST
                    matched[doc_index].add(term)
        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], self.chunks[item[0]]["file"], self.chunks[item[0]]["start_line"]),
        )[:limit]
        return [
            {"index": doc_index, "score": round(score, 4), "matched_terms": sorted(matched[doc_index])}
            for doc_index, score in ranked
        ]


class VectorIndex:
    def __init__(self, chunk_ids: list[str], vectors: np.ndarray) -> None:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.chunk_ids = chunk_ids
        self.matrix = vectors / norms

    def __len__(self) -> int:
        return len(self.chunk_ids)

    def search(self, query_vector: np.ndarray, limit: int = 8) -> list[tuple[str, float]]:
        if len(self.chunk_ids) == 0:
            return []
        norm = np.linalg.norm(query_vector)
        if norm == 0:
            return []
        scores = self.matrix @ (query_vector / norm)
        order = np.argsort(-scores)[:limit]
        return [(self.chunk_ids[int(i)], float(scores[int(i)])) for i in order if scores[int(i)] >= EMBEDDING_MIN_SCORE]


def reciprocal_rank_fusion(rankings: list[list[str]], limit: int) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (RRF_K + position)
    return sorted(scores.items(), key=lambda item: -item[1])[:limit]


def _snippet(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= SNIPPET_LINES:
        return text
    return "\n".join(lines[:SNIPPET_LINES]) + f"\n... ({len(lines) - SNIPPET_LINES} more lines)"


def format_hit(chunk: dict[str, Any], score: float, matched: list[str], method: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk["id"],
        "file": chunk["file"],
        "line": chunk["start_line"],
        "end_line": chunk["end_line"],
        "symbol": chunk["symbol"],
        "symbol_id": chunk["symbol_id"],
        "kind": chunk["kind"],
        "score": round(float(score), 4),
        "matched_terms": matched,
        "method": method,
        "snippet": _snippet(chunk["text"]),
    }


def search_chunks(chunks: list[dict[str, Any]], lexical: LexicalIndex, query: str, limit: int = 8,
                  vector_index: VectorIndex | None = None, query_vector: np.ndarray | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 25))
    lexical_hits = lexical.search(query, limit=max(limit * 3, 10))
    if vector_index is not None and query_vector is not None and len(vector_index):
        vector_hits = vector_index.search(query_vector, limit=max(limit * 3, 10))
        fused = reciprocal_rank_fusion(
            [[chunks[hit["index"]]["id"] for hit in lexical_hits], [chunk_id for chunk_id, _ in vector_hits]],
            limit,
        )
        by_id = {chunk["id"]: index for index, chunk in enumerate(chunks)}
        lexical_terms = {chunks[hit["index"]]["id"]: hit["matched_terms"] for hit in lexical_hits}
        results = []
        for chunk_id, fused_score in fused:
            chunk = chunks[by_id[chunk_id]]
            results.append(format_hit(chunk, fused_score, lexical_terms.get(chunk_id, []), "hybrid"))
        return results
    return [
        format_hit(chunks[hit["index"]], hit["score"], hit["matched_terms"], "lexical")
        for hit in lexical_hits[:limit]
    ]
