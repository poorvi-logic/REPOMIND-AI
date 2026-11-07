from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .errors import NotFoundError
from .index import RepositoryIndex
from .llm import LLMClient

SYSTEM_PROMPT = (
    "You are RepoMind, an assistant that explains Python code. Use only the supplied static facts and source "
    "excerpts. If the supplied material does not show something, say that it is not shown. Never invent files, "
    "functions, classes, call paths or behaviour. Keep exact static relationships separate from name-based guesses, "
    "and say when you are unsure. Write in plain paragraphs without Markdown headings."
)
QA_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + " Answer the question using only the numbered excerpts and the conversation so far. Cite every claim with its "
    "excerpt label such as [S2]. If the excerpts do not answer the question, reply with exactly INSUFFICIENT_EVIDENCE "
    "followed by a short explanation of what is missing."
)
EXPLANATION_GUIDE = (
    "Cover these points in short paragraphs, in this order, and only where the code supports them: what it does; "
    "why it is needed; how it works step by step; what it takes in; what it returns or changes; which other parts of "
    "the code it works with; where it would be used in a real application; and what a developer should understand "
    "about it. Give a concrete example only if you label it as illustrative. Do not invent business rules."
)
MODE_GUIDE = {
    "beginner": "Use plain language and one everyday comparison. Explain any technical term the first time you use it.",
    "developer": "Use precise technical language and name the functions, classes and files involved.",
    "deep_dive": "Cover architecture, control flow, dependencies and edge cases, as far as the excerpts show them.",
}
FALLBACK_NOTE = (
    " Only the structure is shown here. The purpose and real-world use need an AI key in Settings."
)
INSUFFICIENT_EVIDENCE_TEXT = (
    "I could not find code in this project that answers this question. Try naming a function, class, module, "
    "or a more specific term from the code."
)


class AnalysisCache:
    def __init__(self, store: Any, analysis_id: str, model: str) -> None:
        self._store = store
        self._analysis_id = analysis_id
        self._model = model

    def get(self, key: str) -> str | None:
        record = self._store.get_cached(self._analysis_id, f"{self._model}|{key}")
        return record["content"] if record else None

    def put(self, key: str, content: str, created_at: str) -> None:
        self._store.put_cached(self._analysis_id, f"{self._model}|{key}", content, self._model, created_at)


class _NullCache:
    def get(self, key: str) -> None:
        return None

    def put(self, key: str, content: str, created_at: str) -> None:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _response(text: str, mode: str, status: str, model: str | None = None, references: list | None = None,
              **extra: Any) -> dict[str, Any]:
    return {"text": text, "mode": mode, "ai_status": status, "model": model, "references": references or [], **extra}


def _reference(file: str, start: int, end: int, label: str | None = None, symbol_id: str | None = None) -> dict[str, Any]:
    return {"file": file, "start_line": start, "end_line": end, "label": label, "symbol_id": symbol_id}


def _run_model(llm: LLMClient, cache: Any, cache_key: str, system: str, user: str,
               fallback_text: str, references: list, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    cached = cache.get(cache_key)
    if cached is not None:
        return _response(cached, "llm", "ok", llm.model, references, cached=True, **(facts or {}))
    if not llm.enabled:
        return _response(fallback_text + FALLBACK_NOTE, "deterministic", "disabled", None, references, **(facts or {}))
    result = llm.complete(system, user)
    if result.status == "ok" and result.text:
        cache.put(cache_key, result.text, _now())
        return _response(result.text, "llm", "ok", result.model, references, cached=False, **(facts or {}))
    note = f"AI explanation unavailable ({result.status}). Built from static analysis instead.\n\n{fallback_text}{FALLBACK_NOTE}"
    return _response(note, "deterministic", result.status, result.model, references, **(facts or {}))


def explain_file(index: RepositoryIndex, path: str, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    detail = index.file_detail(path)
    source = index.source_text(path)[:14000]
    fallback = _file_fallback(detail)
    user = f"Explain this Python file. {EXPLANATION_GUIDE}\n\nStatic facts:\n{fallback}\n\nFile: {path}\n\nSource:\n{source}"
    references = [_reference(path, 1, max(detail["lines"], 1), label=path)]
    return _run_model(llm, cache, f"file:{path}", SYSTEM_PROMPT, user, fallback, references)


def _file_fallback(detail: dict[str, Any]) -> str:
    classes = [item["name"] for item in detail["classes"]]
    functions = [item["qualname"] for item in detail["symbols"] if item["kind"] in {"function", "nested_function"}]
    methods = [item["qualname"] for item in detail["symbols"] if item["kind"] == "method"]
    imports = sorted({item["module"] or "(relative)" for item in detail["imports"]})
    parts = [f"{detail['path']} has {detail['lines']} lines in module {detail['module']}."]
    parts.append(f"Classes: {', '.join(classes) or 'none'}.")
    parts.append(f"Functions: {', '.join(functions) or 'none'}.")
    parts.append(f"Methods: {', '.join(methods) or 'none'}.")
    parts.append(f"Imported modules: {', '.join(imports) or 'none'}.")
    importers = ", ".join(edge["module"] for edge in detail["module_dependencies"]["imported_by"]) or "none"
    parts.append(f"Modules that import this file: {importers}.")
    if detail["parse_error"]:
        parts.append(f"The file could not be parsed: {detail['parse_error']['message']} at line {detail['parse_error']['line']}.")
    if detail["findings"]:
        parts.append(f"Review checks flagged {len(detail['findings'])} item(s).")
    return " ".join(parts)


def explain_symbol(index: RepositoryIndex, symbol_id: str, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    detail = index.symbol_detail(symbol_id)
    fallback = _symbol_fallback(detail)
    subject = "class and its main methods" if detail["kind"] == "class" else "function"
    user = (
        f"Explain this {subject}. {EXPLANATION_GUIDE}\n\nStatic facts:\n{fallback}\n\nSource:\n{detail['source']['text']}"
    )
    references = [_reference(detail["file"], detail["line"], detail["end_line"], label=detail["qualname"], symbol_id=symbol_id)]
    return _run_model(llm, cache, f"symbol:{symbol_id}", SYSTEM_PROMPT, user, fallback, references)


def _symbol_fallback(detail: dict[str, Any]) -> str:
    args = ", ".join(a["name"] + (f": {a['annotation']}" if a["annotation"] else "") for a in detail["arguments"])
    signature = f"{'async ' if detail['is_async'] else ''}{detail['qualname']}({args})"
    if detail["returns"]:
        signature += f" -> {detail['returns']}"
    parts = [f"Signature: {signature}. Defined at {detail['file']} lines {detail['line']}-{detail['end_line']}."]
    if detail["decorators"]:
        parts.append(f"Decorators: {', '.join(detail['decorators'])}.")
    if detail["docstring"]:
        parts.append(f"Docstring: {detail['docstring']}")
    parts.append(f"Cyclomatic complexity: {detail['complexity']}.")
    confirmed = [c for c in detail["callees"] if c["confidence"] == "confirmed"]
    approximate = [c for c in detail["callees"] if c["confidence"] == "approximate"]
    parts.append("Exact calls: " + (", ".join(f"{c['target_name']} (line {c['line']})" for c in confirmed) or "none") + ".")
    if approximate:
        parts.append("Name-based calls: " + ", ".join(f"{c['target_name']} (line {c['line']})" for c in approximate) + ".")
    parts.append("Called by: " + (", ".join(f"{c['source_name']} (line {c['line']}, {c['confidence']})" for c in detail["callers"]) or "none found") + ".")
    return " ".join(parts)


def explain_architecture(index: RepositoryIndex, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    summary = index.summary()
    dependency = summary["dependency_summary"]
    hubs = ", ".join(f"{h['module']} (used by {h['fan_in']})" for h in dependency["hub_modules"]) or "none"
    cycles = "; ".join(" -> ".join(c["example_cycle"]) for c in index.cycles[:5]) or "none detected"
    entry_like = [m for m in sorted(index.module_to_file) if not index.module_importers.get(m)]
    fallback = (
        f"Project {summary['repository']} has {summary['summary']['python_files']} Python files, "
        f"{summary['summary']['classes']} classes and {summary['summary']['functions']} functions. "
        f"There are {dependency['module_dependencies']} internal module dependencies. Most depended-on modules: {hubs}. "
        f"Import cycles: {cycles}. Modules that nothing in the project imports (possible entry points): "
        f"{', '.join(entry_like[:12]) or 'none'}."
    )
    user = (
        f"Explain how this project is organised. {EXPLANATION_GUIDE} Describe the business purpose only if the "
        f"names and code make it clear; otherwise say it is not shown.\n\nStatic facts:\n{fallback}\n\nModules and imports:\n"
        + "\n".join(
            f"{m} imports {', '.join(sorted({e['target'] for e in index.module_imports.get(m, [])})) or 'nothing internal'}"
            for m in sorted(index.module_to_file)
        )
    )
    references = [_reference(path, 1, max(index.files[path]["lines"], 1), label=module)
                  for module, path in list(index.module_to_file.items())[:12]]
    return _run_model(llm, cache, "architecture", SYSTEM_PROMPT, user, fallback, references)


def explain_module_dependencies(index: RepositoryIndex, module: str, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    if module not in index.module_to_file:
        raise NotFoundError("Module not found in this analysis.")
    facts = index.dependency_summary_for_module(module)
    imports = ", ".join(f"{i['module']} (line {i['line']}{', inside a function' if i['lazy'] else ''})" for i in facts["imports"]) or "no internal modules"
    importers = ", ".join(i["module"] for i in facts["imported_by"]) or "no internal module"
    cycle_note = "It takes part in an import cycle." if facts["in_cycle"] else "It is not part of an import cycle."
    fallback = f"Module {module} ({facts['file']}) imports: {imports}. Imported by: {importers}. {cycle_note}"
    user = f"Explain this module's dependencies and what a change to it would affect. {EXPLANATION_GUIDE}\n\nStatic facts:\n{fallback}"
    references = [_reference(facts["file"], 1, 1, label=module)]
    return _run_model(llm, cache, f"dependencies:{module}", SYSTEM_PROMPT, user, fallback, references, facts={"module": module})


def explain_finding(index: RepositoryIndex, finding_id: str, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    finding = index.finding(finding_id)
    lines = index.files[finding["file"]]["content"].splitlines()
    start = max(1, finding["line"] - 3)
    end = min(len(lines), finding["line"] + 3)
    snippet = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
    fallback = (
        f"{finding['title']} ({finding['rule_id']}, severity {finding['severity']}) at {finding['file']} line "
        f"{finding['line']}. This is a {finding['confidence']} static-analysis match, not a confirmed defect or "
        f"vulnerability. {finding['explanation']} Why it matters: {finding.get('why_it_matters', '')} "
        f"Suggested remediation: {finding['remediation']}"
    )
    user = (
        "Explain this review finding to a developer: what was found, why it may matter, what would need to be true "
        "for it to be a real problem, and how to verify it. It is a heuristic match, not a confirmed vulnerability.\n\n"
        f"Finding: {fallback}\n\nSource around the finding:\n{snippet}"
    )
    references = [_reference(finding["file"], finding["line"], finding["end_line"], label=finding["rule_id"],
                             symbol_id=finding.get("symbol_id"))]
    return _run_model(llm, cache, f"finding:{finding_id}", SYSTEM_PROMPT, user, fallback, references, facts={"finding_id": finding_id})


def explain_flow(index: RepositoryIndex, symbol_id: str, depth: int, llm: LLMClient, cache: Any | None = None) -> dict[str, Any]:
    cache = cache or _NullCache()
    flow = index.call_flow(symbol_id, depth=depth)
    fallback = "Calls made from " + index._symbol_name(symbol_id) + ":\n" + ("\n".join(flow["lines"]) or "No resolvable calls were found.")
    user = (
        f"Describe the order in which this function's calls happen, step by step, using only the call edges below. "
        f"Mark name-based links as likely rather than certain, and say when the flow cannot be determined.\n\n{fallback}"
    )
    symbol = index.symbols[symbol_id]
    references = [_reference(symbol["file"], symbol["line"], symbol["end_line"], label=symbol["qualname"], symbol_id=symbol_id)]
    return _run_model(llm, cache, f"flow:{symbol_id}:{depth}", SYSTEM_PROMPT, user, fallback, references, facts={"flow": flow})


def _context_block(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for number, hit in enumerate(hits, start=1):
        label = f"[S{number}] {hit['file']} lines {hit['line']}-{hit['end_line']}"
        if hit["symbol"]:
            label += f" (symbol: {hit['symbol']})"
        blocks.append(f"{label}\n{hit['snippet']}")
    return "\n\n".join(blocks)


def _history_block(history: list[dict[str, Any]] | None) -> str:
    if not history:
        return ""
    lines = []
    for item in history[-6:]:
        speaker = "User" if item["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {item['content'][:500]}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def _deterministic_answer(hits: list[dict[str, Any]]) -> str:
    lines = [
        "No AI key is connected, so this answer lists the code that matched your question. Review it to find the answer:"
    ]
    for number, hit in enumerate(hits[:3], start=1):
        label = f"{hit['file']} lines {hit['line']}-{hit['end_line']}"
        if hit["symbol"]:
            label += f" ({hit['symbol']})"
        lines.append(f"[S{number}] {label}")
    return "\n".join(lines)


def follow_up_suggestions(hits: list[dict[str, Any]]) -> list[str]:
    symbol_hit = next((hit for hit in hits if hit.get("symbol")), None)
    if symbol_hit:
        name = symbol_hit["symbol"].split(".")[-1]
        return [f"What calls {name}?", f"Walk me through {name} step by step.", f"What does {name} depend on?"]
    if hits:
        return [f"What else happens in {hits[0]['file']}?"]
    return []


def plan_answer(index: RepositoryIndex, question: str, hits: list[dict[str, Any]], llm: LLMClient,
                retrieval_method: str, mode: str = "developer", history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    graph_facts = index.graph_facts(question)
    references = [_reference(h["file"], h["line"], h["end_line"], label=f"S{n}", symbol_id=h.get("symbol_id"))
                  for n, h in enumerate(hits, start=1)]
    level = mode if mode in MODE_GUIDE else "developer"
    plan: dict[str, Any] = {
        "hits": hits, "graph_facts": graph_facts, "retrieval": retrieval_method,
        "references": references, "explanation_mode": level, "system": None, "user": None,
    }
    if not hits:
        plan["kind"] = "insufficient"
    elif not llm.enabled:
        plan["kind"] = "deterministic"
    else:
        plan["kind"] = "llm"
        facts_block = "\n".join(f"- {fact}" for fact in graph_facts) or "- none"
        plan["system"] = QA_SYSTEM_PROMPT
        plan["user"] = (
            f"{_history_block(history)}Question: {question}\n\nAnswer style: {MODE_GUIDE[level]}\n\n"
            f"Numbered source excerpts:\n{_context_block(hits)}\n\nStatic structure facts:\n{facts_block}"
        )
    return plan


def _base_result(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence": plan["hits"], "graph_facts": plan["graph_facts"], "retrieval": plan["retrieval"],
        "references": plan["references"], "explanation_mode": plan["explanation_mode"],
        "suggestions": follow_up_suggestions(plan["hits"]),
    }


def result_insufficient(plan: dict[str, Any]) -> dict[str, Any]:
    return {**_base_result(plan), "answer": INSUFFICIENT_EVIDENCE_TEXT, "mode": "insufficient-evidence",
            "ai_status": "not_called", "model": None, "insufficient_evidence": True, "citations": [], "uncited": False}


def result_deterministic(plan: dict[str, Any], status: str, model: str | None) -> dict[str, Any]:
    shown = plan["references"][:3]
    citations = [reference | {"file": plan["hits"][n]["file"]} for n, reference in enumerate(shown)]
    return {**_base_result(plan), "answer": _deterministic_answer(plan["hits"]), "mode": "deterministic",
            "ai_status": status, "model": model, "insufficient_evidence": False, "citations": citations, "uncited": False}


def result_llm(plan: dict[str, Any], text: str, model: str | None) -> dict[str, Any]:
    if text.startswith("INSUFFICIENT_EVIDENCE"):
        answer = text.replace("INSUFFICIENT_EVIDENCE", "", 1).strip() or INSUFFICIENT_EVIDENCE_TEXT
        return {**_base_result(plan), "answer": answer, "mode": "insufficient-evidence", "ai_status": "ok",
                "model": model, "insufficient_evidence": True, "citations": [], "uncited": False}
    numbers = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", text) if 1 <= int(n) <= len(plan["hits"])})
    citations = [plan["references"][n - 1] | {"file": plan["hits"][n - 1]["file"]} for n in numbers]
    return {**_base_result(plan), "answer": text, "mode": "llm", "ai_status": "ok", "model": model,
            "insufficient_evidence": False, "citations": citations, "uncited": not numbers}


def answer_question(index: RepositoryIndex, question: str, hits: list[dict[str, Any]], llm: LLMClient,
                    retrieval_method: str, mode: str = "developer", history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    plan = plan_answer(index, question, hits, llm, retrieval_method, mode, history)
    if plan["kind"] == "insufficient":
        return result_insufficient(plan)
    if plan["kind"] == "deterministic":
        return result_deterministic(plan, "disabled", None)
    outcome = llm.complete(plan["system"], plan["user"])
    if outcome.status != "ok" or not outcome.text:
        return result_deterministic(plan, outcome.status, outcome.model)
    return result_llm(plan, outcome.text, outcome.model)


def vector_for_query(llm: LLMClient, query: str) -> np.ndarray | None:
    status, vectors = llm.embed([query])
    if status != "ok" or not vectors:
        return None
    return np.asarray(vectors[0], dtype=np.float32)
