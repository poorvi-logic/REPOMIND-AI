from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from typing import Any, Callable

from ..index import RepositoryIndex
from ..risks import RULES

MODE_LABELS = {
    "architecture": "Architecture Detective",
    "function": "Function Detective",
    "workflow": "Workflow Challenge",
    "bug": "Bug Detective",
    "dependency": "Dependency Challenge",
    "risk": "Risk Detective",
}
DIFFICULTIES = ("beginner", "intermediate", "advanced")
BUG_RULES = ("RM-SEC-002", "RM-SQL-001", "RM-ERR-001", "RM-SEC-005", "RM-SEC-003", "RM-FILE-001")
EXACT_RESOLUTIONS = {"same_module", "enclosing_scope", "import", "self_method", "module_attribute", "class_attribute"}
CALLABLE_KINDS = ("function", "method")
NO_QUESTIONS = {
    "architecture": "No module has exactly one clear import, so there is no architecture question to build.",
    "function": "No function here has a docstring, a single exact call, or a parameter list to ask about.",
    "workflow": "No function makes three or more exact calls to project code, so there is no order to practise.",
    "bug": "The risk checks found no items of the kinds used for Bug Detective.",
    "dependency": "No module has a single clear importer, so there is no dependency chain to explore.",
    "risk": "The risk checks found no issues in this project.",
}


def _digest(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _build(mode: str, difficulty: str, kind: str, prompt: str, texts: list[str], correct_sequence: list[str],
           explanation: str, hint: str, evidence: list[dict[str, Any]], module: str | None,
           excerpt: dict[str, Any] | None) -> dict[str, Any]:
    material = _digest(mode, difficulty, kind, prompt, repr(evidence))
    order = list(range(len(texts)))
    random.Random(int(material[:12], 16)).shuffle(order)
    options = []
    option_for_text: dict[str, str] = {}
    for position, source_index in enumerate(order):
        option_id = f"o{position}"
        options.append({"id": option_id, "text": texts[source_index]})
        option_for_text[texts[source_index]] = option_id
    answer = [option_for_text[correct_sequence[0]]] if kind == "choice" else [option_for_text[step] for step in correct_sequence]
    return {
        "id": material[:12], "mode": mode, "mode_label": MODE_LABELS[mode], "difficulty": difficulty,
        "module": module, "kind": kind, "prompt": prompt, "excerpt": excerpt, "options": options,
        "answer": answer, "explanation": explanation, "hint": hint, "evidence": evidence,
        "source": "built from this project's analysis data",
    }


def _choice(mode: str, difficulty: str, prompt: str, correct: str, distractors: list[str], explanation: str,
            hint: str, evidence: list[dict[str, Any]], module: str | None,
            excerpt: dict[str, Any] | None = None) -> dict[str, Any] | None:
    unique: list[str] = []
    for text in distractors:
        if text and text != correct and text not in unique:
            unique.append(text)
    if len(unique) < 2:
        return None
    return _build(mode, difficulty, "choice", prompt, [correct] + unique[:3], [correct], explanation, hint,
                  evidence, module, excerpt)


def _line_evidence(file: str, line: int, label: str, end_line: int | None = None) -> dict[str, Any]:
    return {"file": file, "start_line": line, "end_line": end_line or line, "label": label}


def architecture_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in index.module_edges:
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]].append(edge)
    modules = sorted(index.module_to_file)
    questions = []
    for source in modules:
        edges = outgoing.get(source, [])
        if len(edges) != 1 or edges[0]["target"] == source:
            continue
        edge = edges[0]
        target = edge["target"]
        pool = sorted((m for m in modules if m not in {source, target}), key=lambda m: _digest(source, m))
        question = _choice(
            "architecture", "beginner", f"Which module does `{source}` import directly?", target, pool,
            f"`{source}` imports `{target}` on line {edge['line']} of {edge['source_file']}. Imports are read directly "
            f"from the code, so this is an exact dependency.",
            f"Read the import lines near the top of {edge['source_file']}.",
            [_line_evidence(edge["source_file"], edge["line"], f"import of {target}")], source)
        if question:
            questions.append(question)
    for target in modules:
        edges = incoming.get(target, [])
        if len(edges) != 1 or edges[0]["source"] == target:
            continue
        edge = edges[0]
        importer = edge["source"]
        pool = sorted((m for m in modules if m not in {importer, target}), key=lambda m: _digest(target, m))
        question = _choice(
            "architecture", "intermediate", f"Which module imports `{target}` directly?", importer, pool,
            f"`{importer}` imports `{target}` on line {edge['line']} of {edge['source_file']}. It is the only module "
            f"in this project that does so.",
            f"Look for an import line that names `{target}`.",
            [_line_evidence(edge["source_file"], edge["line"], f"import of {target}")], target)
        if question:
            questions.append(question)
    return questions


def class_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    from collections import Counter

    classes = sorted((s for s in index.symbols.values() if s["kind"] == "class"), key=lambda s: (s["file"], s["line"]))
    method_counts = Counter(s["name"] for s in index.symbols.values() if s["kind"] == "method")
    questions = []
    for cls in classes:
        evidence = [_line_evidence(cls["file"], cls["start_line"], cls["qualname"], cls["end_line"])]
        if cls.get("docstring"):
            pool = sorted((s["qualname"] for s in classes if s["id"] != cls["id"]), key=lambda n: _digest(cls["id"], n))
            question = _choice(
                "function", "beginner", f"What is the job of the class `{cls['qualname']}`?", cls["docstring"],
                [s["docstring"] for s in classes if s["id"] != cls["id"] and s.get("docstring")],
                f"Its docstring says: \"{cls['docstring']}\". The class is defined on lines {cls['start_line']} to "
                f"{cls['end_line']} of {cls['file']}. Its methods show how it does this.",
                "Start with the first line of the class docstring.", evidence, cls["module"])
            if question:
                questions.append(question)
        for method in sorted((s for s in index.symbols.values() if s["kind"] == "method" and s["class_name"] == cls["qualname"]),
                             key=lambda s: s["line"]):
            if method_counts[method["name"]] != 1 or method["name"].startswith("__") or method["decorators"]:
                continue
            pool = sorted((s["qualname"] for s in classes if s["id"] != cls["id"]), key=lambda n: _digest(method["id"], n))
            question = _choice(
                "function", "beginner", f"Which class defines the method `{method['name']}`?", cls["qualname"], pool,
                f"`{method['qualname']}` is defined on line {method['line']} of {method['file']}, inside `{cls['qualname']}`.",
                "Look for the class whose body contains a def with this name.",
                [_line_evidence(method["file"], method["start_line"], method["qualname"], method["end_line"])], cls["module"])
            if question:
                questions.append(question)
            break
    return questions


def function_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    callables = sorted((s for s in index.symbols.values() if s["kind"] in CALLABLE_KINDS),
                       key=lambda s: (s["file"], s["line"]))
    documented = [s for s in index.symbols.values() if s["kind"] in ("function", "method", "class") and s.get("docstring")]
    questions = []
    for symbol in callables:
        evidence = [_line_evidence(symbol["file"], symbol["start_line"], symbol["qualname"], symbol["end_line"])]
        if symbol.get("docstring"):
            pool = sorted((s["docstring"] for s in documented if s["id"] != symbol["id"]), key=lambda d: _digest(symbol["id"], d))
            question = _choice(
                "function", "beginner", f"What does `{symbol['qualname']}` do?", symbol["docstring"], pool,
                f"Its docstring says: \"{symbol['docstring']}\". The function is defined on lines {symbol['start_line']} "
                f"to {symbol['end_line']} of {symbol['file']}. Read the body to confirm the docstring matches the code.",
                "Start with the first line of the function's docstring.", evidence, symbol["module"])
            if question:
                questions.append(question)
        inputs = [a["name"] for a in symbol["arguments"] if a["name"] not in ("self", "cls")]
        count = len(inputs)
        numbers = [str(n) for n in sorted({count + 1, count + 2, max(count - 1, 0)} - {count})]
        question = _choice(
            "function", "beginner", f"How many inputs does `{symbol['qualname']}` take? Do not count self or cls.",
            str(count), numbers,
            f"Its signature lists {count} input(s){': ' + ', '.join(inputs) if inputs else ''}.",
            "Count the names between the brackets in the def line.", evidence, symbol["module"])
        if question:
            questions.append(question)
        targets: dict[str, dict[str, Any]] = {}
        for edge in index.outgoing_calls.get(symbol["id"], []):
            if edge["target"] in index.symbols and edge["confidence"] == "confirmed" and edge["resolution"] in EXACT_RESOLUTIONS:
                targets.setdefault(edge["target"], edge)
        if len(targets) == 1:
            target_id, edge = next(iter(targets.items()))
            target_name = index.symbols[target_id]["qualname"]
            pool = sorted((s["qualname"] for s in callables if s["id"] not in {symbol["id"], target_id}),
                          key=lambda n: _digest(symbol["id"], n))
            question = _choice(
                "function", "intermediate", f"Which function does `{symbol['qualname']}` call directly?", target_name, pool,
                f"Line {edge['line']} of {symbol['file']} calls `{target_name}`. The name resolves exactly, through an "
                f"import or a definition in the same module.",
                f"Scan the body for a call on a single line.",
                evidence + [_line_evidence(symbol["file"], edge["line"], f"call to {target_name}")], symbol["module"])
            if question:
                questions.append(question)
        callers: dict[str, dict[str, Any]] = {}
        for edge in index.incoming_calls.get(symbol["id"], []):
            caller = index.symbols.get(edge["source"])
            if caller and caller["kind"] in CALLABLE_KINDS and edge["confidence"] == "confirmed":
                callers.setdefault(edge["source"], edge)
        if len(callers) == 1:
            caller_id = next(iter(callers))
            caller = index.symbols[caller_id]
            pool = sorted((s["qualname"] for s in callables if s["id"] not in {symbol["id"], caller_id}),
                          key=lambda n: _digest(symbol["id"], n))
            question = _choice(
                "function", "intermediate", f"Which function calls `{symbol['qualname']}` directly?", caller["qualname"], pool,
                f"`{caller['qualname']}` calls `{symbol['qualname']}` on line {callers[caller_id]['line']} of {caller['file']}.",
                "Search the project for the function's name followed by an opening bracket.",
                evidence + [_line_evidence(caller["file"], callers[caller_id]["line"], f"call to {symbol['qualname']}")],
                symbol["module"])
            if question:
                questions.append(question)
    questions.extend(class_questions(index))
    return questions


def workflow_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    questions = []
    for symbol in sorted((s for s in index.symbols.values() if s["kind"] in CALLABLE_KINDS), key=lambda s: (s["file"], s["line"])):
        first_call: dict[str, dict[str, Any]] = {}
        for edge in index.outgoing_calls.get(symbol["id"], []):
            target = index.symbols.get(edge["target"]) if edge["target"] else None
            if target and target["kind"] != "module" and edge["confidence"] == "confirmed" and edge["resolution"] in EXACT_RESOLUTIONS:
                first_call.setdefault(edge["target"], edge)
        ordered = sorted(first_call.values(), key=lambda e: e["line"])[:5]
        names = [index.symbols[e["target"]]["qualname"] for e in ordered]
        if len(names) < 3 or len(set(names)) != len(names):
            continue
        difficulty = "intermediate" if len(names) == 3 else "advanced"
        lines = ", ".join(str(e["line"]) for e in ordered)
        evidence = [_line_evidence(symbol["file"], symbol["start_line"], symbol["qualname"], symbol["end_line"])]
        evidence += [_line_evidence(symbol["file"], e["line"], f"call to {index.symbols[e['target']]['qualname']}") for e in ordered]
        questions.append(_build(
            "workflow", difficulty, "order", f"Put these calls from `{symbol['qualname']}` in the order they run.",
            names, names,
            f"The calls sit on lines {lines} of {symbol['file']}. Statements run from top to bottom, so the line order is "
            f"the run order. If a call sits inside an if or a loop, it may not run every time.",
            "Read the function from top to bottom and note the line where each call appears.",
            evidence, symbol["module"], None))
    return questions


def bug_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    titles = [RULES[rule]["title"] for rule in BUG_RULES]
    eligible = sorted((f for f in index.findings.values() if f["rule_id"] in BUG_RULES),
                      key=lambda f: (f["file"], f["line"]))[:6]
    questions = []
    for finding in eligible:
        lines = index.files[finding["file"]]["content"].splitlines()
        start = max(1, finding["line"] - 2)
        end = min(len(lines), finding["end_line"] + 2)
        excerpt = {"file": finding["file"], "start_line": start, "text": "\n".join(lines[start - 1:end])}
        pool = [title for title in titles if title != finding["title"]]
        difficulty = "intermediate" if finding["rule_id"] in ("RM-SEC-002", "RM-SQL-001", "RM-SEC-003") else "beginner"
        question = _choice(
            "bug", difficulty, "Read this excerpt. Which concern does it raise?", finding["title"], pool,
            f"{finding['explanation']} Why it matters: {finding.get('why_it_matters', '')} This is a heuristic match, so check "
            f"whether the values involved can come from outside the program.",
            "Look at the function call or the operation on the highlighted lines.",
            [_line_evidence(finding["file"], finding["line"], finding["rule_id"], finding["end_line"])],
            index.files[finding["file"]]["module"], excerpt)
        if question:
            questions.append(question)
    return questions


def dependency_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    importers = index.module_importers
    modules = sorted(index.module_to_file)
    questions = []
    for module in modules:
        direct = sorted({e["source"] for e in importers.get(module, [])})
        if len(direct) != 1:
            continue
        importer = direct[0]
        edge = next(e for e in importers[module] if e["source"] == importer)
        pool = sorted((m for m in modules if m not in {module, importer} and m not in direct), key=lambda m: _digest(module, m))
        question = _choice(
            "dependency", "intermediate", f"If `{module}` changes, which module is directly affected?", importer, pool,
            f"`{importer}` imports `{module}` on line {edge['line']} of {edge['source_file']}. That is an exact dependency, "
            f"so a change to `{module}` can reach `{importer}` straight away.",
            f"Find the module whose import lines name `{module}`.",
            [_line_evidence(edge["source_file"], edge["line"], f"import of {module}")], module)
        if question:
            questions.append(question)
        second = sorted({e["source"] for e in importers.get(importer, [])})
        if len(second) == 1 and second[0] not in {module, importer}:
            far = second[0]
            far_edge = next(e for e in importers[importer] if e["source"] == far)
            pool = sorted((m for m in modules if m not in {module, importer, far} and m not in second), key=lambda m: _digest(far, m))
            question = _choice(
                "dependency", "advanced", f"If `{module}` changes, which module could be affected two steps away?", far, pool,
                f"`{importer}` depends on `{module}`, and `{far}` imports `{importer}` on line {far_edge['line']} of "
                f"{far_edge['source_file']}. A change can travel through `{importer}` to `{far}`.",
                f"Follow the chain of imports: first find who imports `{module}`, then who imports that module.",
                [_line_evidence(edge["source_file"], edge["line"], f"import of {module}"),
                 _line_evidence(far_edge["source_file"], far_edge["line"], f"import of {importer}")], module)
            if question:
                questions.append(question)
    return questions


def risk_questions(index: RepositoryIndex) -> list[dict[str, Any]]:
    remediations = {rule: meta["remediation"] for rule, meta in RULES.items()}
    questions = []
    for finding in sorted(index.findings.values(), key=lambda f: (f["file"], f["line"]))[:6]:
        correct = finding["remediation"]
        pool = sorted({text for rule, text in remediations.items() if rule != finding["rule_id"] and text != correct},
                      key=lambda text: _digest(finding["id"], text))
        question = _choice(
            "risk", "intermediate", f"`{finding['title']}` was flagged in `{finding['file']}`. Which fix fits best?",
            correct, pool,
            f"Why it matters: {finding.get('why_it_matters', '')} This is a heuristic review item, so confirm it in context "
            f"before changing the code.",
            "Think about what the flagged line does and where its input comes from.",
            [_line_evidence(finding["file"], finding["line"], finding["rule_id"], finding["end_line"])],
            index.files[finding["file"]]["module"])
        if question:
            questions.append(question)
    return questions


GENERATORS: dict[str, Callable[[RepositoryIndex], list[dict[str, Any]]]] = {
    "architecture": architecture_questions,
    "function": function_questions,
    "workflow": workflow_questions,
    "bug": bug_questions,
    "dependency": dependency_questions,
    "risk": risk_questions,
}


def generate(index: RepositoryIndex, mode: str, difficulty: str | None = None,
             module: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    if not index.symbols and not index.findings:
        return [], "This project has no Python code to learn from. CodeQuest works with Python files."
    names = list(GENERATORS) if mode == "mixed" else [mode]
    found: list[dict[str, Any]] = []
    for name in names:
        for question in GENERATORS[name](index):
            if difficulty and question["difficulty"] != difficulty:
                continue
            if module and question["module"] != module:
                continue
            found.append(question)
    if not found:
        reason = NO_QUESTIONS.get(mode, NO_QUESTIONS["risk"])
        if difficulty:
            reason += f" Nothing at {difficulty} level was found."
        return [], reason
    return found, None
