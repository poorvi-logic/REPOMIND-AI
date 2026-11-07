from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..errors import InputError, NotFoundError
from ..index import RepositoryIndex
from .generator import DIFFICULTIES, MODE_LABELS, generate
from .grading import grade

PUBLIC_FIELDS = ("id", "mode", "mode_label", "difficulty", "module", "kind", "prompt", "excerpt", "options", "source")
ALL_MODES = ["mixed", *MODE_LABELS]
WORDING_SYSTEM = (
    "You help a developer learn a codebase. Rewrite the prompt and explanation you are given in friendly, plain English "
    "that a second-year student can follow. Keep every name in names_to_keep exactly as written, inside backticks. Do not "
    "add facts or change what is correct. If the word heuristic appears, keep it. Reply only with a JSON object with the "
    "keys prompt and explanation."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public(question: dict[str, Any]) -> dict[str, Any]:
    return {key: question[key] for key in PUBLIC_FIELDS}


class LearningService:
    def __init__(self, store: Any) -> None:
        self._store = store

    def overview(self, analysis_id: str, index: RepositoryIndex) -> dict[str, Any]:
        return {
            "modes": [{"id": "mixed", "label": "Mixed practice"}, *[{"id": key, "label": label} for key, label in MODE_LABELS.items()]],
            "difficulties": list(DIFFICULTIES),
            "modules": sorted(index.module_to_file),
            "progress": self.progress(analysis_id),
        }

    def generate(self, analysis_id: str, index: RepositoryIndex, mode: str, difficulty: str | None,
                 module: str | None, count: int, llm: Any = None) -> dict[str, Any]:
        if mode not in ALL_MODES:
            raise InputError("Choose a practice mode from the list.")
        if difficulty and difficulty not in DIFFICULTIES:
            raise InputError("Choose beginner, intermediate or advanced.")
        questions, reason = generate(index, mode, difficulty, module)
        answered = self._store.answered_question_ids(analysis_id)
        pending = [q for q in questions if q["id"] not in answered]
        chosen = (pending or questions)[:count]
        if llm is not None and llm.enabled:
            worded = {q["id"]: self._worded(q, llm) for q in chosen if q["id"] not in answered}
            questions = [worded.get(q["id"], q) for q in questions]
            chosen = [worded.get(q["id"], q) for q in chosen]
        self._store.save_learning_questions(analysis_id, [q for q in questions if q["id"] not in answered], _now())
        return {"questions": [_public(q) for q in chosen], "available": len(questions), "reason": reason}

    def _worded(self, question: dict[str, Any], llm: Any) -> dict[str, Any]:
        original = question["prompt"] + " " + question["explanation"]
        names = sorted(set(re.findall(r"`([^`]+)`", original)))
        payload = {"prompt": question["prompt"], "explanation": question["explanation"], "names_to_keep": names}
        outcome = llm.complete(WORDING_SYSTEM, json.dumps(payload, ensure_ascii=False), max_output_tokens=500)
        if outcome.status != "ok" or not outcome.text:
            return question
        start, end = outcome.text.find("{"), outcome.text.rfind("}")
        if start < 0 or end <= start:
            return question
        try:
            data = json.loads(outcome.text[start:end + 1])
        except ValueError:
            return question
        prompt, explanation = data.get("prompt"), data.get("explanation")
        if not isinstance(prompt, str) or not isinstance(explanation, str) or not prompt.strip() or not explanation.strip():
            return question
        combined = prompt + " " + explanation
        if any(f"`{name}`" not in combined for name in names):
            return question
        if "heuristic" in question["explanation"] and "heuristic" not in combined:
            return question
        return {**question, "prompt": prompt.strip(), "explanation": explanation.strip(),
                "source": "worded with AI from this project's analysis data"}

    def hint(self, analysis_id: str, question_id: str) -> dict[str, Any]:
        question = self._question(analysis_id, question_id)
        self._store.mark_hint(analysis_id, question_id)
        return {"hint": question["hint"]}

    def answer(self, analysis_id: str, question_id: str, selected: list[str] | None,
               order: list[str] | None) -> dict[str, Any]:
        question = self._question(analysis_id, question_id)
        previous = self._store.get_learning_attempt(analysis_id, question_id)
        if previous:
            result = previous
            already = True
        else:
            hint_used = self._store.hint_used(analysis_id, question_id)
            result = grade(question, selected, order, hint_used)
            self._store.save_learning_attempt(analysis_id, question_id, result, _now())
            already = False
        texts = {option["id"]: option["text"] for option in question["options"]}
        return {
            "question_id": question_id,
            "already_answered": already,
            "correct": result["correct"],
            "points": result["points"],
            "matched_positions": result["matched_positions"],
            "your_answer": [texts[item] for item in result["chosen"]],
            "correct_answer": [texts[item] for item in question["answer"]],
            "explanation": question["explanation"],
            "evidence": question["evidence"],
            "why_it_is_right": question["explanation"] if result["correct"] else None,
        }

    def progress(self, analysis_id: str) -> dict[str, Any]:
        attempts = self._store.list_learning_attempts(analysis_id)
        questions = {q["id"]: q for q in self._store.list_learning_question_payloads(analysis_id)}
        answered = len(attempts)
        correct = sum(1 for item in attempts if item["correct"])
        points = round(sum(item["points"] for item in attempts), 2)
        by_mode: dict[str, dict[str, int]] = {}
        for item in attempts:
            question = questions.get(item["question_id"])
            if not question:
                continue
            bucket = by_mode.setdefault(question["mode"], {"answered": 0, "correct": 0})
            bucket["answered"] += 1
            bucket["correct"] += 1 if item["correct"] else 0
        review = []
        for item in attempts:
            question = questions.get(item["question_id"])
            if not question or item["correct"]:
                continue
            texts = {option["id"]: option["text"] for option in question["options"]}
            review.append({
                "question_id": question["id"], "mode": question["mode"], "mode_label": question["mode_label"],
                "prompt": question["prompt"], "correct_answer": [texts[i] for i in question["answer"]],
                "explanation": question["explanation"], "evidence": question["evidence"],
            })
        return {
            "answered": answered,
            "correct": correct,
            "points": points,
            "accuracy": round(correct / answered, 2) if answered else None,
            "generated": len(questions),
            "by_mode": by_mode,
            "review": review,
        }

    def _question(self, analysis_id: str, question_id: str) -> dict[str, Any]:
        question = self._store.get_learning_question(analysis_id, question_id)
        if question is None:
            raise NotFoundError("Question not found. Generate questions first.")
        return question
