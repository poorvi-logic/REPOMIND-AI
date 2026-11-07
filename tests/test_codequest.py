from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.index import RepositoryIndex
from app.ingestion import IngestionLimits
from app.learning.generator import MODE_LABELS, generate
from app.main import create_app
from app.pipeline import analyze_directory
from tests.conftest import SAMPLE_DIR, build_zip, make_settings
from tests.fakes import FakeLLM

MODULES_FROM_SAMPLE = {"main", "orders", "payment", "notifications", "utils", "auth", "database", "api", "config", "reports"}


def _index(path: Path, analysis_id: str = "codequest0001") -> RepositoryIndex:
    return RepositoryIndex(analyze_directory(path, analysis_id=analysis_id, repository_name="t", source_type="local",
                                             source_ref="t", limits=IngestionLimits()))


def _zip_of(directory: Path, tmp_path: Path) -> Path:
    archive = tmp_path / f"{directory.name}.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(directory.rglob("*.py")):
            bundle.write(path, arcname=path.relative_to(directory).as_posix())
    return archive


def _assert_traceable(index: RepositoryIndex, question: dict) -> None:
    assert question["evidence"], f"question {question['id']} has no evidence"
    for item in question["evidence"]:
        assert item["file"] in index.files, f"unknown file in evidence: {item['file']}"
        lines = index.files[item["file"]]["content"].splitlines()
        assert 1 <= item["start_line"] <= item["end_line"] <= len(lines), f"bad line range: {item}"
    option_ids = {option["id"] for option in question["options"]}
    assert set(question["answer"]) <= option_ids
    if question["kind"] == "choice":
        assert len(question["answer"]) == 1
        assert len(question["options"]) >= 3
    else:
        assert sorted(question["answer"]) == sorted(option_ids)


def test_every_generated_question_points_to_real_source_evidence(sample_dir: Path):
    index = _index(sample_dir)
    seen_modes = set()
    for mode in MODE_LABELS:
        questions, _ = generate(index, mode)
        for question in questions:
            _assert_traceable(index, question)
            seen_modes.add(mode)
    assert {"architecture", "function", "workflow", "bug", "dependency", "risk"} <= seen_modes


def test_architecture_answers_match_the_import_statements(sample_dir: Path):
    index = _index(sample_dir)
    questions, _ = generate(index, "architecture")
    assert questions
    for question in questions:
        evidence_file = question["evidence"][0]["file"]
        answer = next(o["text"] for o in question["options"] if o["id"] == question["answer"][0])
        if question["prompt"].startswith("Which module does"):
            assert answer in index.files[evidence_file]["content"].replace(".", " ") or answer.split(".")[-1] in index.files[evidence_file]["content"]
        else:
            assert index.files[evidence_file]["module"] == answer


def test_workflow_order_matches_the_line_order_in_the_source(sample_dir: Path):
    index = _index(sample_dir)
    questions, _ = generate(index, "workflow")
    assert questions
    for question in questions:
        call_evidence = question["evidence"][1:]
        call_lines = [item["start_line"] for item in call_evidence]
        assert call_lines == sorted(call_lines)
        assert all(question["evidence"][0]["start_line"] < line <= question["evidence"][0]["end_line"] for line in call_lines)
        texts = {option["id"]: option["text"] for option in question["options"]}
        answered_order = [texts[option_id] for option_id in question["answer"]]
        assert answered_order == [item["label"].replace("call to ", "") for item in call_evidence]


def test_bug_questions_only_use_evidence_backed_findings(sample_dir: Path):
    index = _index(sample_dir)
    questions, _ = generate(index, "bug")
    assert questions
    for question in questions:
        assert question["excerpt"] is not None
        assert question["evidence"][0]["label"] in {"RM-SEC-002", "RM-SQL-001", "RM-ERR-001", "RM-SEC-005", "RM-SEC-003", "RM-FILE-001"}
        assert "heuristic" in question["explanation"]


def test_questions_change_when_a_different_repository_is_used(sample_dir: Path, tmp_path: Path):
    sample_questions = {q["prompt"] for q in generate(_index(sample_dir), "function")[0]}
    other = tmp_path / "other"
    (other / "pkg").mkdir(parents=True)
    (other / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (other / "pkg" / "ledger.py").write_text(
        "def post_entry(account, amount):\n    \"\"\"Record a debit or credit on an account.\"\"\"\n"
        "    check_amount(amount)\n    return account\n\n"
        "def check_amount(amount):\n    \"\"\"Reject negative amounts.\"\"\"\n    return amount >= 0\n",
        encoding="utf-8",
    )
    other_index = _index(other, "otherrepo0001")
    other_questions = generate(other_index, "function")[0]
    assert other_questions
    other_prompts = {q["prompt"] for q in other_questions}
    assert other_prompts != sample_questions
    assert any("post_entry" in prompt or "check_amount" in prompt for prompt in other_prompts)
    for question in other_questions:
        _assert_traceable(other_index, question)


def test_answers_are_checked_against_the_stored_key_and_scored_once(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    generated = client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "architecture", "count": 3}).json()
    assert generated["questions"]
    question = generated["questions"][0]
    assert "answer" not in question and "explanation" not in question and "evidence" not in question
    hint = client.post(f"/api/analyses/{analysis_id}/learning/questions/{question['id']}/hint").json()
    assert hint["hint"]
    wrong_option = next(o["id"] for o in question["options"])
    first = client.post(f"/api/analyses/{analysis_id}/learning/questions/{question['id']}/answer", json={"selected": [wrong_option]}).json()
    assert first["already_answered"] is False
    assert first["explanation"] and first["evidence"]
    second = client.post(f"/api/analyses/{analysis_id}/learning/questions/{question['id']}/answer", json={"selected": [wrong_option]}).json()
    assert second["already_answered"] is True
    progress = client.get(f"/api/analyses/{analysis_id}/learning/progress").json()
    assert progress["answered"] == 1
    assert len(progress["review"]) == (0 if first["correct"] else 1)


def test_correct_answer_with_hint_earns_half_points_and_wrong_answer_earns_none(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    generated = client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "function", "count": 10}).json()
    store = client.app.state.services.store
    questions = [store.get_learning_question(analysis_id, q["id"]) for q in generated["questions"]]
    hinted, plain = questions[0], questions[1]
    client.post(f"/api/analyses/{analysis_id}/learning/questions/{hinted['id']}/hint")
    correct = client.post(f"/api/analyses/{analysis_id}/learning/questions/{hinted['id']}/answer",
                          json={"selected": hinted["answer"]}).json()
    assert correct["correct"] is True and correct["points"] == 0.5
    wrong_choice = next(o["id"] for o in plain["options"] if o["id"] not in plain["answer"])
    wrong = client.post(f"/api/analyses/{analysis_id}/learning/questions/{plain['id']}/answer",
                        json={"selected": [wrong_choice]}).json()
    assert wrong["correct"] is False and wrong["points"] == 0


def test_order_questions_need_every_step_exactly_once(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    generated = client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "workflow", "count": 5}).json()
    if not generated["questions"]:
        pytest.skip("this repository has no workflow with three exact calls")
    question = generated["questions"][0]
    partial = client.post(f"/api/analyses/{analysis_id}/learning/questions/{question['id']}/answer",
                          json={"order": [question["options"][0]["id"]]})
    assert partial.status_code == 400


def test_unknown_question_and_bad_mode_are_rejected(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    assert client.post(f"/api/analyses/{analysis_id}/learning/questions/abcdef123456/hint").status_code == 404
    assert client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "magic"}).status_code == 422


def test_repository_without_python_is_handled_gracefully(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = build_zip(tmp_path / "notes.zip", {"notes/readme.txt": "hello"})
    with archive.open("rb") as handle:
        response = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")})
    assert response.status_code == 400


def test_repository_with_no_questions_explains_why(tmp_path: Path):
    (tmp_path / "lonely.py").write_text("x = 1\n", encoding="utf-8")
    index = _index(tmp_path, "lonelyrepo0001")
    questions, reason = generate(index, "workflow")
    assert questions == []
    assert "three" in reason


def test_findings_keep_their_why_it_matters_text_after_storage(sample_dir: Path, tmp_path: Path):
    from app.store import Store

    analysis = analyze_directory(sample_dir, analysis_id="storedwhy0001", repository_name="s", source_type="local",
                                 source_ref="s", limits=IngestionLimits())
    store = Store(tmp_path / "db.sqlite")
    store.save_analysis(analysis)
    reloaded = store.load_analysis("storedwhy0001")
    assert reloaded["findings"]
    assert all(item["why_it_matters"] for item in reloaded["findings"])
    store.close()


def test_existing_databases_gain_the_new_column(tmp_path: Path):
    import sqlite3

    from app.store import Store

    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE findings (analysis_id TEXT, id TEXT, rule_id TEXT, legacy_rule TEXT, title TEXT, "
                       "category TEXT, severity TEXT, confidence TEXT, file TEXT, line INTEGER, end_line INTEGER, "
                       "evidence TEXT, explanation TEXT, remediation TEXT, symbol_id TEXT)")
    connection.commit()
    connection.close()
    store = Store(database)
    columns = {row["name"] for row in store._connection.execute("PRAGMA table_info(findings)")}
    assert "why_it_matters" in columns
    store.close()


def test_class_questions_use_real_class_and_method_names(sample_dir: Path):
    index = _index(sample_dir)
    prompts = [q["prompt"] for q in generate(index, "function")[0]]
    assert any(prompt == "Which class defines the method `create_order`?" for prompt in prompts)


class _EchoWordingLLM(FakeLLM):
    def complete(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900):
        import json as _json
        from app.llm import LLMResult
        data = _json.loads(user_prompt)
        return LLMResult("ok", _json.dumps({"prompt": "Let's look at this. " + data["prompt"],
                                            "explanation": "Here is why. " + data["explanation"]}), "fake-model")


class _DroppingNamesLLM(FakeLLM):
    def complete(self, system_prompt: str, user_prompt: str, max_output_tokens: int = 900):
        import json as _json
        from app.llm import LLMResult
        return LLMResult("ok", _json.dumps({"prompt": "A friendly question.", "explanation": "A friendly answer."}), "fake-model")


def test_ai_wording_keeps_names_and_answer_key_and_is_labelled(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    client.app.state.services.llm = _EchoWordingLLM()
    batch = client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "architecture", "count": 2}).json()
    worded = batch["questions"][0]
    assert worded["prompt"].startswith("Let's look at this.")
    assert worded["source"] == "worded with AI from this project's analysis data"
    stored = client.app.state.services.store.get_learning_question(analysis_id, worded["id"])
    assert stored["answer"] and stored["evidence"]


def test_ai_wording_is_rejected_when_it_drops_a_name(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    archive = _zip_of(SAMPLE_DIR, tmp_path)
    with archive.open("rb") as handle:
        analysis_id = client.post("/api/analyses/upload", files={"file": (archive.name, handle, "application/zip")}).json()["analysis_id"]
    client.app.state.services.llm = _DroppingNamesLLM()
    batch = client.post(f"/api/analyses/{analysis_id}/learning/questions", json={"mode": "architecture", "count": 2}).json()
    assert batch["questions"]
    assert all(q["source"] == "built from this project's analysis data" for q in batch["questions"])
    assert all(q["prompt"] != "A friendly question." for q in batch["questions"])


def test_learning_questions_cannot_be_read_or_answered_through_another_project(tmp_path: Path):
    client = TestClient(create_app(make_settings(tmp_path / "data")))
    first = _zip_of(SAMPLE_DIR, tmp_path)
    with first.open("rb") as handle:
        first_id = client.post("/api/analyses/upload", files={"file": (first.name, handle, "application/zip")}).json()["analysis_id"]
    other = build_zip(tmp_path / "other_project.zip", {"other/app.py": "def run():\n    return 1\n"})
    with other.open("rb") as handle:
        second_id = client.post("/api/analyses/upload", files={"file": (other.name, handle, "application/zip")}).json()["analysis_id"]
    batch = client.post(f"/api/analyses/{first_id}/learning/questions", json={"mode": "architecture", "count": 1}).json()
    question_id = batch["questions"][0]["id"]
    assert client.post(f"/api/analyses/{second_id}/learning/questions/{question_id}/hint").status_code == 404
    assert client.post(f"/api/analyses/{second_id}/learning/questions/{question_id}/answer", json={"selected": ["o0"]}).status_code == 404
    progress = client.get(f"/api/analyses/{second_id}/learning/progress").json()
    assert progress["answered"] == 0
