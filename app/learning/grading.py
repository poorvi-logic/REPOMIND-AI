from __future__ import annotations

from typing import Any

from ..errors import InputError


def grade(question: dict[str, Any], selected: list[str] | None, order: list[str] | None, hint_used: bool) -> dict[str, Any]:
    expected = question["answer"]
    option_ids = {option["id"] for option in question["options"]}
    if question["kind"] == "choice":
        if not selected or len(selected) != 1 or selected[0] not in option_ids:
            raise InputError("Choose one of the options.")
        chosen = list(selected)
        correct = chosen == expected
        matched = 1 if correct else 0
    else:
        if not order or sorted(order) != sorted(option_ids):
            raise InputError("Place every option in an order before checking.")
        chosen = list(order)
        correct = chosen == expected
        matched = sum(1 for given, wanted in zip(chosen, expected) if given == wanted)
    points = 0.0 if not correct else (0.5 if hint_used else 1.0)
    return {"correct": correct, "points": points, "chosen": chosen, "matched_positions": matched, "hint_used": hint_used}
