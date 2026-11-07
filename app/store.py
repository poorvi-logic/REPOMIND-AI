from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .errors import NotFoundError

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    commit_sha TEXT,
    created_at TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    dependency_summary_json TEXT NOT NULL,
    cycles_json TEXT NOT NULL,
    unresolved_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_files (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    module TEXT NOT NULL,
    is_package INTEGER NOT NULL,
    lines INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    parse_error_json TEXT,
    imports_json TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (analysis_id, path)
);
CREATE TABLE IF NOT EXISTS symbols (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    file TEXT NOT NULL,
    module TEXT NOT NULL,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    kind TEXT NOT NULL,
    class_name TEXT,
    is_async INTEGER NOT NULL,
    is_nested INTEGER NOT NULL,
    method_type TEXT,
    line INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    length INTEGER NOT NULL,
    complexity INTEGER NOT NULL,
    returns TEXT,
    docstring TEXT,
    decorators_json TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    bases_json TEXT NOT NULL,
    calls_json TEXT NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE TABLE IF NOT EXISTS edges (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT,
    target_name TEXT,
    line INTEGER,
    resolution TEXT,
    confidence TEXT,
    lazy INTEGER NOT NULL DEFAULT 0,
    names_json TEXT NOT NULL DEFAULT '[]',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    source_file TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_analysis ON edges(analysis_id, kind);
CREATE TABLE IF NOT EXISTS findings (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    legacy_rule TEXT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    evidence TEXT NOT NULL,
    explanation TEXT NOT NULL,
    remediation TEXT NOT NULL,
    symbol_id TEXT,
    PRIMARY KEY (analysis_id, id)
);
CREATE TABLE IF NOT EXISTS chunks (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    file TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    symbol_id TEXT,
    symbol TEXT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (analysis_id, model, chunk_id)
);
CREATE TABLE IF NOT EXISTS reports (
    analysis_id TEXT PRIMARY KEY REFERENCES analyses(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jira_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT REFERENCES analyses(id) ON DELETE SET NULL,
    finding_id TEXT,
    project_key TEXT NOT NULL,
    issue_key TEXT NOT NULL,
    issue_url TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_cache (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, cache_key)
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    mode TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_questions (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    mode TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    module TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE TABLE IF NOT EXISTS learning_attempts (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    correct INTEGER NOT NULL,
    points REAL NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, question_id)
);
CREATE TABLE IF NOT EXISTS learning_hints (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    PRIMARY KEY (analysis_id, question_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class Store:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(SCHEMA)
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(findings)")}
        if "why_it_matters" not in columns:
            self._connection.execute("ALTER TABLE findings ADD COLUMN why_it_matters TEXT NOT NULL DEFAULT ''")
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def save_analysis(self, result: dict[str, Any]) -> None:
        analysis_id = result["analysis_id"]
        with self._lock, self._connection:
            connection = self._connection
            connection.execute(
                "INSERT INTO analyses (id, repository, source_type, source_ref, commit_sha, created_at, summary_json,"
                " warnings_json, dependency_summary_json, cycles_json, unresolved_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (analysis_id, result["repository"], result["source_type"], result["source_ref"], result.get("commit"),
                 result["created_at"], _dump(result["summary"]), _dump(result["warnings"]),
                 _dump(result["dependency_summary"]), _dump(result["cycles"]), _dump(result["unresolved_references"])),
            )
            connection.executemany(
                "INSERT INTO source_files VALUES (?,?,?,?,?,?,?,?,?)",
                [(analysis_id, item["path"], item["module"], int(item["is_package"]), item["lines"],
                  item["size_bytes"], _dump(item["parse_error"]) if item["parse_error"] else None,
                  _dump(item["imports"]), item["content"]) for item in result["files"]],
            )
            connection.executemany(
                "INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(analysis_id, item["id"], item["file"], item["module"], item["name"], item["qualname"],
                  item["kind"], item.get("class_name"), int(item.get("is_async", False)),
                  int(item.get("is_nested", False)), item.get("method_type"), item.get("line", 0),
                  item.get("start_line", 0), item.get("end_line", 0), item.get("length", 0),
                  item.get("complexity", 1), item.get("returns"), item.get("docstring"),
                  _dump(item.get("decorators", [])), _dump(item.get("arguments", [])),
                  _dump(item.get("bases", [])), _dump(item.get("calls", [])))
                 for item in result["symbols"]],
            )
            connection.executemany(
                "INSERT INTO edges (analysis_id, kind, source, target, target_name, line, resolution, confidence,"
                " lazy, names_json, candidates_json, source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(analysis_id, edge["kind"], edge["source"], edge.get("target"), edge.get("target_name"),
                  edge.get("line"), edge.get("resolution"), edge.get("confidence"), int(bool(edge.get("lazy", False))),
                  _dump(edge.get("names", [])), _dump(edge.get("candidates", [])), edge.get("source_file"))
                 for edge in result["edges"]],
            )
            connection.executemany(
                "INSERT INTO findings (analysis_id, id, rule_id, legacy_rule, title, category, severity, confidence, file, line, end_line, evidence, explanation, remediation, symbol_id, why_it_matters) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(analysis_id, item["id"], item["rule_id"], item.get("legacy_rule"), item["title"], item["category"],
                  item["severity"], item["confidence"], item["file"], item["line"], item["end_line"],
                  item["evidence"], item["explanation"], item["remediation"], item.get("symbol_id"), item.get("why_it_matters", ""))
                 for item in result["findings"]],
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                [(analysis_id, item["id"], item["file"], item["start_line"], item["end_line"], item.get("symbol_id"),
                  item.get("symbol"), item["kind"], item["text"]) for item in result["chunks"]],
            )

    def list_analyses(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT a.*, (SELECT 1 FROM reports r WHERE r.analysis_id = a.id) AS has_report "
                "FROM analyses a ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._meta(row) for row in rows]

    def _meta(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "analysis_id": row["id"],
            "repository": row["repository"],
            "source_type": row["source_type"],
            "source_ref": row["source_ref"],
            "commit": row["commit_sha"],
            "created_at": row["created_at"],
            "summary": _load(row["summary_json"], {}),
            "warnings": _load(row["warnings_json"], []),
            "has_report": bool(row["has_report"]) if "has_report" in row.keys() else False,
        }

    def get_analysis_meta(self, analysis_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT a.*, (SELECT 1 FROM reports r WHERE r.analysis_id = a.id) AS has_report "
                "FROM analyses a WHERE a.id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Analysis not found.")
        return self._meta(row)

    def load_analysis(self, analysis_id: str) -> dict[str, Any]:
        meta = self.get_analysis_meta(analysis_id)
        with self._lock:
            connection = self._connection
            files = [
                {"path": row["path"], "module": row["module"], "is_package": bool(row["is_package"]),
                 "lines": row["lines"], "size_bytes": row["size_bytes"],
                 "parse_error": _load(row["parse_error_json"], None), "imports": _load(row["imports_json"], []),
                 "content": row["content"]}
                for row in connection.execute("SELECT * FROM source_files WHERE analysis_id = ? ORDER BY path", (analysis_id,))
            ]
            symbols = [
                {"id": row["id"], "file": row["file"], "module": row["module"], "name": row["name"],
                 "qualname": row["qualname"], "kind": row["kind"], "class_name": row["class_name"],
                 "is_async": bool(row["is_async"]), "is_nested": bool(row["is_nested"]),
                 "method_type": row["method_type"], "line": row["line"], "start_line": row["start_line"],
                 "end_line": row["end_line"], "length": row["length"], "complexity": row["complexity"],
                 "returns": row["returns"], "docstring": row["docstring"],
                 "decorators": _load(row["decorators_json"], []), "arguments": _load(row["arguments_json"], []),
                 "bases": _load(row["bases_json"], []), "calls": _load(row["calls_json"], [])}
                for row in connection.execute("SELECT * FROM symbols WHERE analysis_id = ? ORDER BY file, line", (analysis_id,))
            ]
            edges = [
                {"kind": row["kind"], "source": row["source"], "target": row["target"],
                 "target_name": row["target_name"], "line": row["line"], "resolution": row["resolution"],
                 "confidence": row["confidence"], "lazy": bool(row["lazy"]), "names": _load(row["names_json"], []),
                 "candidates": _load(row["candidates_json"], []), "source_file": row["source_file"]}
                for row in connection.execute("SELECT * FROM edges WHERE analysis_id = ?", (analysis_id,))
            ]
            findings = [
                {"id": row["id"], "rule_id": row["rule_id"], "legacy_rule": row["legacy_rule"], "title": row["title"],
                 "category": row["category"], "severity": row["severity"], "confidence": row["confidence"],
                 "file": row["file"], "line": row["line"], "end_line": row["end_line"], "evidence": row["evidence"],
                 "explanation": row["explanation"], "remediation": row["remediation"], "symbol_id": row["symbol_id"],
                 "why_it_matters": row["why_it_matters"]}
                for row in connection.execute("SELECT * FROM findings WHERE analysis_id = ? ORDER BY rowid", (analysis_id,))
            ]
            chunks = [
                {"id": row["id"], "file": row["file"], "start_line": row["start_line"], "end_line": row["end_line"],
                 "symbol_id": row["symbol_id"], "symbol": row["symbol"], "kind": row["kind"], "text": row["text"]}
                for row in connection.execute("SELECT * FROM chunks WHERE analysis_id = ? ORDER BY file, start_line", (analysis_id,))
            ]
            summary_row = connection.execute(
                "SELECT dependency_summary_json, cycles_json, unresolved_json FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        return {
            **meta,
            "summary": meta["summary"],
            "files": files,
            "symbols": symbols,
            "edges": edges,
            "findings": findings,
            "chunks": chunks,
            "dependency_summary": _load(summary_row["dependency_summary_json"], {}),
            "cycles": _load(summary_row["cycles_json"], []),
            "unresolved_references": _load(summary_row["unresolved_json"], []),
        }

    def delete_analysis(self, analysis_id: str) -> str | None:
        with self._lock, self._connection:
            report = self._connection.execute("SELECT path FROM reports WHERE analysis_id = ?", (analysis_id,)).fetchone()
            cursor = self._connection.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
            if cursor.rowcount == 0:
                raise NotFoundError("Analysis not found.")
        return report["path"] if report else None

    def save_embeddings(self, analysis_id: str, model: str, chunk_ids: list[str], matrix: np.ndarray) -> None:
        rows = [
            (analysis_id, model, chunk_id, int(matrix.shape[1]), matrix[index].astype(np.float32).tobytes())
            for index, chunk_id in enumerate(chunk_ids)
        ]
        with self._lock, self._connection:
            self._connection.executemany(
                "INSERT OR REPLACE INTO chunk_embeddings (analysis_id, model, chunk_id, dimensions, vector) VALUES (?,?,?,?,?)",
                rows,
            )

    def load_embeddings(self, analysis_id: str, model: str) -> tuple[list[str], np.ndarray] | None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT chunk_id, dimensions, vector FROM chunk_embeddings WHERE analysis_id = ? AND model = ? ORDER BY chunk_id",
                (analysis_id, model),
            ).fetchall()
        if not rows:
            return None
        chunk_ids = [row["chunk_id"] for row in rows]
        matrix = np.vstack([np.frombuffer(row["vector"], dtype=np.float32, count=row["dimensions"]) for row in rows])
        return chunk_ids, matrix

    def set_report(self, analysis_id: str, path: str, created_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO reports (analysis_id, path, created_at) VALUES (?,?,?)",
                (analysis_id, path, created_at),
            )

    def get_report_path(self, analysis_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute("SELECT path FROM reports WHERE analysis_id = ?", (analysis_id,)).fetchone()
        return row["path"] if row else None

    def record_jira_ticket(self, *, analysis_id: str | None, finding_id: str | None, project_key: str,
                           issue_key: str, issue_url: str, summary: str, created_at: str) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO jira_tickets (analysis_id, finding_id, project_key, issue_key, issue_url, summary, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (analysis_id, finding_id, project_key, issue_key, issue_url, summary, created_at),
            )
        return {"id": cursor.lastrowid, "analysis_id": analysis_id, "finding_id": finding_id, "project_key": project_key,
                "issue_key": issue_key, "issue_url": issue_url, "summary": summary, "created_at": created_at}

    def list_jira_tickets(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM jira_tickets ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def find_jira_ticket(self, analysis_id: str, finding_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jira_tickets WHERE analysis_id = ? AND finding_id = ? ORDER BY id DESC LIMIT 1",
                (analysis_id, finding_id),
            ).fetchone()
        return {key: row[key] for key in row.keys()} if row else None

    def get_cached(self, analysis_id: str, cache_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT content, model, created_at FROM ai_cache WHERE analysis_id = ? AND cache_key = ?",
                (analysis_id, cache_key),
            ).fetchone()
        return {"content": row["content"], "model": row["model"], "created_at": row["created_at"]} if row else None

    def put_cached(self, analysis_id: str, cache_key: str, content: str, model: str, created_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO ai_cache (analysis_id, cache_key, content, model, created_at) VALUES (?,?,?,?,?)",
                (analysis_id, cache_key, content, model, created_at),
            )

    def create_conversation(self, analysis_id: str, conversation_id: str, title: str, created_at: str) -> dict[str, Any]:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO conversations (id, analysis_id, title, created_at) VALUES (?,?,?,?)",
                (conversation_id, analysis_id, title, created_at),
            )
        return self.get_conversation(conversation_id)

    def list_conversations(self, analysis_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
                "FROM conversations c WHERE c.analysis_id = ? ORDER BY c.created_at DESC", (analysis_id,)
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            raise NotFoundError("Conversation not found.")
        return {key: row[key] for key in row.keys()}

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))

    def delete_conversation(self, conversation_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            if cursor.rowcount == 0:
                raise NotFoundError("Conversation not found.")

    def add_message(self, conversation_id: str, role: str, content: str, mode: str | None,
                    payload: dict[str, Any] | None, created_at: str) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO messages (conversation_id, role, content, mode, payload_json, created_at) VALUES (?,?,?,?,?,?)",
                (conversation_id, role, content, mode, _dump(payload) if payload is not None else None, created_at),
            )
        return {"id": cursor.lastrowid, "conversation_id": conversation_id, "role": role, "content": content,
                "mode": mode, "payload": payload, "created_at": created_at}

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            ).fetchall()
        return [{"id": row["id"], "conversation_id": row["conversation_id"], "role": row["role"],
                 "content": row["content"], "mode": row["mode"],
                 "payload": _load(row["payload_json"], None), "created_at": row["created_at"]} for row in rows]

    def save_learning_questions(self, analysis_id: str, questions: list[dict[str, Any]], created_at: str) -> None:
        with self._lock, self._connection:
            self._connection.executemany(
                "INSERT OR REPLACE INTO learning_questions (analysis_id, id, mode, difficulty, module, payload_json, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                [(analysis_id, q["id"], q["mode"], q["difficulty"], q["module"], _dump(q), created_at) for q in questions],
            )

    def get_learning_question(self, analysis_id: str, question_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM learning_questions WHERE analysis_id = ? AND id = ?", (analysis_id, question_id)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_learning_question_payloads(self, analysis_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM learning_questions WHERE analysis_id = ?", (analysis_id,)
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def answered_question_ids(self, analysis_id: str) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT question_id FROM learning_attempts WHERE analysis_id = ?", (analysis_id,)
            ).fetchall()
        return {row["question_id"] for row in rows}

    def mark_hint(self, analysis_id: str, question_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO learning_hints (analysis_id, question_id) VALUES (?,?)", (analysis_id, question_id)
            )

    def hint_used(self, analysis_id: str, question_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM learning_hints WHERE analysis_id = ? AND question_id = ?", (analysis_id, question_id)
            ).fetchone()
        return row is not None

    def get_learning_attempt(self, analysis_id: str, question_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT result_json FROM learning_attempts WHERE analysis_id = ? AND question_id = ?", (analysis_id, question_id)
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def save_learning_attempt(self, analysis_id: str, question_id: str, result: dict[str, Any], created_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO learning_attempts (analysis_id, question_id, correct, points, result_json, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (analysis_id, question_id, int(result["correct"]), result["points"], _dump(result), created_at),
            )

    def list_learning_attempts(self, analysis_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT question_id, correct, points, result_json FROM learning_attempts WHERE analysis_id = ?", (analysis_id,)
            ).fetchall()
        return [{"question_id": row["question_id"], "correct": bool(row["correct"]), "points": row["points"],
                 "chosen": json.loads(row["result_json"])["chosen"]} for row in rows]

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute("SELECT key, value_json FROM settings").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connection:
            self._connection.executemany(
                "INSERT OR REPLACE INTO settings (key, value_json) VALUES (?, ?)",
                [(key, _dump(value)) for key, value in values.items()],
            )
        return self.get_settings()
