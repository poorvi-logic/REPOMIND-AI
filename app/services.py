from __future__ import annotations

import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import numpy as np

from .config import MB, Settings
from .errors import InputError, NotFoundError
from .index import RepositoryIndex
from .ingestion import (
    IngestionLimits, analysis_workspace, clone_repository, detect_repository_root, extract_python_archive,
    parse_github_url, remove_stale_workspaces, save_upload_stream, count_other_file_types,
)
from .intelligence import (
    AnalysisCache, answer_question, explain_architecture, explain_file, explain_finding, explain_flow,
    explain_module_dependencies, explain_symbol, plan_answer, result_deterministic, result_insufficient, result_llm,
    vector_for_query,
)
from .llm import classify_error
from .learning.service import LearningService
from .jira import JiraClient, JiraCredentialStore, JiraCredentials, credentials_from_settings, normalize_site_url
from .llm import LLMClient
from .pipeline import analyze_directory, new_analysis_id
from .reports import build_report, write_report
from .retrieval import VectorIndex
from .store import Store
from .tickets import make_ticket_draft
from .jira import ISSUE_KEY_PATTERN, PROJECT_KEY_PATTERN

EMBED_BATCH_SIZE = 64
EMBED_CHARS = 6000
INDEX_CACHE_SIZE = 4
DEFAULT_PREFERENCES: dict[str, Any] = {
    "default_risk_severity": "info",
    "graph_max_nodes": 150,
    "retrieval_mode": "lexical",
    "show_approximate_edges": False,
}
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


def _safe_name(filename: str) -> str:
    base = Path(filename or "upload.zip").name
    return _UNSAFE_NAME.sub("_", base)[:120] or "upload.zip"


class AppServices:
    def __init__(self, settings: Settings, llm: LLMClient | None = None, store: Store | None = None) -> None:
        self.settings = settings
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        settings.reports_dir.mkdir(parents=True, exist_ok=True)
        remove_stale_workspaces(settings.workspace_dir)
        self.store = store or Store(settings.database_path)
        self.llm = llm or LLMClient(settings.openai_api_key, settings.openai_model,
                                    settings.openai_embedding_model, settings.openai_timeout_seconds)
        self.jira = JiraCredentialStore(credentials_from_settings(settings))
        self.limits = IngestionLimits(
            max_python_files=settings.max_python_files,
            max_file_bytes=settings.max_file_kb * 1024,
            max_repository_bytes=settings.max_repository_mb * MB,
        )
        self.learning = LearningService(self.store)
        self._indexes: OrderedDict[str, RepositoryIndex] = OrderedDict()
        self._vectors: OrderedDict[str, VectorIndex] = OrderedDict()
        self._lock = threading.RLock()

    def _persist(self, result: dict[str, Any]) -> dict[str, Any]:
        if result["summary"]["python_files"] == 0:
            raise InputError("No Python files were found in the repository.")
        self.store.save_analysis(result)
        return self.store.get_analysis_meta(result["analysis_id"])

    def analyze_zip(self, stream: BinaryIO, filename: str) -> dict[str, Any]:
        safe_name = _safe_name(filename)
        if not safe_name.lower().endswith(".zip"):
            raise InputError("Upload a .zip file.")
        analysis_id = new_analysis_id(safe_name)
        with analysis_workspace(self.settings.workspace_dir, analysis_id) as workspace:
            archive_path = workspace / "upload.zip"
            save_upload_stream(stream, archive_path, self.settings.max_upload_mb * MB)
            source_dir = workspace / "source"
            extraction = extract_python_archive(archive_path, source_dir, self.limits)
            root = detect_repository_root(source_dir)
            result = analyze_directory(
                root, analysis_id=analysis_id, repository_name=Path(safe_name).stem or "uploaded-repository",
                source_type="zip", source_ref=safe_name, limits=self.limits, warnings=extraction.warnings,
                other_file_types=extraction.other_file_types,
            )
        return self._persist(result)

    def analyze_github(self, url: str) -> dict[str, Any]:
        repository = parse_github_url(url)
        analysis_id = new_analysis_id(repository.full_name)
        with analysis_workspace(self.settings.workspace_dir, analysis_id) as workspace:
            clone_dir = workspace / "clone"
            commit = clone_repository(repository.clone_url, clone_dir, self.settings.clone_timeout_seconds)
            root = detect_repository_root(clone_dir)
            result = analyze_directory(
                root, analysis_id=analysis_id, repository_name=repository.full_name, source_type="github",
                source_ref=f"https://github.com/{repository.full_name}", limits=self.limits, commit=commit,
                other_file_types=count_other_file_types(root),
            )
        return self._persist(result)

    def index(self, analysis_id: str) -> RepositoryIndex:
        with self._lock:
            cached = self._indexes.get(analysis_id)
            if cached is not None:
                self._indexes.move_to_end(analysis_id)
                return cached
        index = RepositoryIndex(self.store.load_analysis(analysis_id))
        with self._lock:
            self._indexes[analysis_id] = index
            while len(self._indexes) > INDEX_CACHE_SIZE:
                self._indexes.popitem(last=False)
        return index

    def delete_analysis(self, analysis_id: str) -> None:
        report_path = self.store.delete_analysis(analysis_id)
        if report_path:
            Path(report_path).unlink(missing_ok=True)
        with self._lock:
            self._indexes.pop(analysis_id, None)
            self._vectors.pop(analysis_id, None)

    @property
    def retrieval_method(self) -> str:
        return "hybrid" if self.settings.retrieval_mode == "hybrid" and self.llm.enabled else "lexical"

    def _vector_index(self, index: RepositoryIndex) -> tuple[VectorIndex | None, str | None]:
        if self.retrieval_method != "hybrid":
            return None, None
        with self._lock:
            cached = self._vectors.get(index.analysis_id)
            if cached is not None:
                return cached, None
        model = self.llm.embedding_model
        chunk_ids = [chunk["id"] for chunk in index.chunks]
        stored = self.store.load_embeddings(index.analysis_id, model)
        if stored is not None and sorted(stored[0]) == sorted(chunk_ids):
            vector_index = VectorIndex(stored[0], stored[1])
        else:
            vectors: list[list[float]] = []
            for start in range(0, len(index.chunks), EMBED_BATCH_SIZE):
                batch = index.chunks[start:start + EMBED_BATCH_SIZE]
                status, embedded = self.llm.embed([chunk["text"][:EMBED_CHARS] for chunk in batch])
                if status != "ok" or embedded is None:
                    return None, f"Embeddings unavailable ({status}); used lexical retrieval."
                vectors.extend(embedded)
            if not vectors:
                return None, None
            matrix = np.asarray(vectors, dtype=np.float32)
            self.store.save_embeddings(index.analysis_id, model, chunk_ids, matrix)
            vector_index = VectorIndex(chunk_ids, matrix)
        with self._lock:
            self._vectors[index.analysis_id] = vector_index
            while len(self._vectors) > INDEX_CACHE_SIZE:
                self._vectors.popitem(last=False)
        return vector_index, None

    def search(self, analysis_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        index = self.index(analysis_id)
        vector_index, note = self._vector_index(index)
        query_vector = None
        if vector_index is not None:
            query_vector = vector_for_query(self.llm, query)
            if query_vector is None:
                note = "Query embedding unavailable; used lexical retrieval."
        method = "hybrid" if vector_index is not None and query_vector is not None else "lexical"
        hits = index.search(query, limit=limit,
                            vector_index=vector_index if method == "hybrid" else None,
                            query_vector=query_vector if method == "hybrid" else None)
        return {"query": query, "method": method, "note": note, "results": hits}

    def ask(self, analysis_id: str, question: str) -> dict[str, Any]:
        index = self.index(analysis_id)
        retrieval = self.search(analysis_id, question, limit=8)
        answer = answer_question(index, question, retrieval["results"], self.llm, retrieval["method"])
        return {**answer, "question": question, "retrieval_note": retrieval["note"]}

    def learning_overview(self, analysis_id: str) -> dict[str, Any]:
        return self.learning.overview(analysis_id, self.index(analysis_id))

    def learning_generate(self, analysis_id: str, mode: str, difficulty: str | None, module: str | None, count: int) -> dict[str, Any]:
        return self.learning.generate(analysis_id, self.index(analysis_id), mode, difficulty, module, count, self.llm)

    def learning_hint(self, analysis_id: str, question_id: str) -> dict[str, Any]:
        return self.learning.hint(analysis_id, question_id)

    def learning_answer(self, analysis_id: str, question_id: str, selected: list[str] | None, order: list[str] | None) -> dict[str, Any]:
        return self.learning.answer(analysis_id, question_id, selected, order)

    def learning_progress(self, analysis_id: str) -> dict[str, Any]:
        self.store.get_analysis_meta(analysis_id)
        return self.learning.progress(analysis_id)

    def create_conversation(self, analysis_id: str, title: str | None = None) -> dict[str, Any]:
        self.store.get_analysis_meta(analysis_id)
        return self.store.create_conversation(analysis_id, new_analysis_id(analysis_id + (title or "")),
                                              title or "New conversation", utc_now())

    def list_conversations(self, analysis_id: str) -> list[dict[str, Any]]:
        self.store.get_analysis_meta(analysis_id)
        return self.store.list_conversations(analysis_id)

    def conversation_detail(self, analysis_id: str, conversation_id: str) -> dict[str, Any]:
        conversation = self._owned_conversation(analysis_id, conversation_id)
        return {**conversation, "messages": self.store.list_messages(conversation_id)}

    def delete_conversation(self, analysis_id: str, conversation_id: str) -> None:
        self._owned_conversation(analysis_id, conversation_id)
        self.store.delete_conversation(conversation_id)

    def _owned_conversation(self, analysis_id: str, conversation_id: str) -> dict[str, Any]:
        conversation = self.store.get_conversation(conversation_id)
        if conversation["analysis_id"] != analysis_id:
            raise NotFoundError("Conversation not found.")
        return conversation

    def stream_message(self, analysis_id: str, conversation_id: str, question: str, mode: str) -> Iterator[dict[str, Any]]:
        conversation = self._owned_conversation(analysis_id, conversation_id)
        history = self.store.list_messages(conversation_id)
        index = self.index(analysis_id)
        retrieval = self.search(analysis_id, _retrieval_query(question, history), limit=8)
        plan = plan_answer(index, question, retrieval["results"], self.llm, retrieval["method"], mode, history)
        self.store.add_message(conversation_id, "user", question, mode, None, utc_now())
        yield {"type": "context", "retrieval": retrieval["method"], "note": retrieval["note"],
               "citations": plan["references"][:8]}
        if plan["kind"] != "llm":
            final = result_insufficient(plan) if plan["kind"] == "insufficient" else result_deterministic(plan, "disabled", None)
            yield {"type": "delta", "text": final["answer"]}
        else:
            pieces: list[str] = []
            try:
                for piece in self.llm.stream(plan["system"], plan["user"]):
                    pieces.append(piece)
                    yield {"type": "delta", "text": piece}
                text = "".join(pieces).strip()
                final = result_llm(plan, text, self.llm.model) if text else result_deterministic(plan, "empty_response", self.llm.model)
            except Exception as exc:
                final = result_deterministic(plan, classify_error(exc), self.llm.model)
                yield {"type": "delta", "text": "\n\n" + final["answer"]}
        if conversation["title"] == "New conversation":
            self.store.rename_conversation(conversation_id, _title_from(question))
        payload = {key: final[key] for key in ("mode", "ai_status", "model", "citations", "suggestions",
                                               "insufficient_evidence", "uncited", "explanation_mode", "retrieval")}
        saved = self.store.add_message(conversation_id, "assistant", final["answer"], mode, payload, utc_now())
        yield {"type": "done", "message": saved, "suggestions": final["suggestions"]}

    def send_message(self, analysis_id: str, conversation_id: str, question: str, mode: str) -> dict[str, Any]:
        done: dict[str, Any] = {}
        for event in self.stream_message(analysis_id, conversation_id, question, mode):
            if event["type"] == "done":
                done = event
        return done

    def cache(self, analysis_id: str) -> AnalysisCache:
        return AnalysisCache(self.store, analysis_id, self.llm.model)

    def explain(self, analysis_id: str, kind: str, target: str | int | None = None) -> dict[str, Any]:
        index = self.index(analysis_id)
        cache = self.cache(analysis_id)
        if kind == "file":
            return explain_file(index, str(target), self.llm, cache)
        if kind == "symbol":
            return explain_symbol(index, str(target), self.llm, cache)
        if kind == "architecture":
            return explain_architecture(index, self.llm, cache)
        if kind == "module":
            return explain_module_dependencies(index, str(target), self.llm, cache)
        if kind == "finding":
            return explain_finding(index, str(target), self.llm, cache)
        if kind == "flow":
            symbol_id, depth = target
            return explain_flow(index, symbol_id, depth, self.llm, cache)
        raise NotFoundError("Unknown explanation type.")

    def report_path(self, analysis_id: str) -> Path:
        existing = self.store.get_report_path(analysis_id)
        if existing and Path(existing).exists():
            return Path(existing)
        analysis = self.store.load_analysis(analysis_id)
        path = write_report(build_report(analysis), self.settings.reports_dir, analysis_id)
        self.store.set_report(analysis_id, str(path), datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return path

    def preferences(self) -> dict[str, Any]:
        stored = self.store.get_settings()
        merged = {**DEFAULT_PREFERENCES, "retrieval_mode": self.settings.retrieval_mode, **stored}
        return merged

    def update_preferences(self, values: dict[str, Any]) -> dict[str, Any]:
        self.store.update_settings(values)
        return self.preferences()

    def connect_jira(self, site_url: str, email: str, api_token: str) -> dict[str, Any]:
        normalized = normalize_site_url(site_url, self.settings.jira_allow_any_host)
        credentials = JiraCredentials(base_url=normalized, email=email.strip(), api_token=api_token.strip())
        client = JiraClient(credentials)
        try:
            identity = client.myself()
        finally:
            client.close()
        self.jira.set_session(credentials)
        return {**self.jira.public_status(), "identity": identity}

    def disconnect_jira(self) -> dict[str, Any]:
        self.jira.clear_session()
        return self.jira.public_status()

    def jira_client(self) -> JiraClient:
        credentials, _ = self.jira.current()
        if credentials is None:
            raise InputError("Jira is not connected. Enter credentials on the Jira page or set JIRA_* variables.", 409)
        return JiraClient(credentials)

    def jira_preview(self, analysis_id: str, finding_id: str, project_key: str, issue_type: str) -> dict[str, Any]:
        if not PROJECT_KEY_PATTERN.match(project_key):
            raise InputError("Enter a valid Jira project key, such as OPS or WEB.")
        index = self.index(analysis_id)
        finding = index.finding(finding_id)
        draft = make_ticket_draft(finding, index.analysis["repository"], analysis_id, project_key, issue_type)
        return {**draft, "analysis_id": analysis_id}

    def ai_status(self) -> dict[str, Any]:
        return {
            "connected": self.llm.enabled,
            "source": self.llm.key_source,
            "model": self.llm.model,
            "embedding_model": self.llm.embedding_model,
        }

    def connect_ai(self, api_key: str) -> dict[str, Any]:
        candidate = LLMClient(api_key, self.llm.model, self.llm.embedding_model, self.settings.openai_timeout_seconds)
        outcome = candidate.check_key()
        if outcome != "ok":
            messages = {
                "auth_error": "OpenAI rejected this API key.",
                "rate_limited": "OpenAI is rate limiting requests. Try again in a minute.",
                "timeout": "OpenAI did not respond in time.",
            }
            raise InputError(messages.get(outcome, "Could not reach OpenAI. Check your internet connection."))
        self.llm.connect(api_key)
        return self.ai_status()

    def disconnect_ai(self) -> dict[str, Any]:
        self.llm.disconnect()
        return self.ai_status()

    def jira_create(self, analysis_id: str, finding_id: str, project_key: str, issue_type: str) -> dict[str, Any]:
        draft = self.jira_preview(analysis_id, finding_id, project_key, issue_type)
        existing = self.store.find_jira_ticket(analysis_id, finding_id)
        if existing:
            raise InputError(f"A Jira issue already exists for this finding: {existing['issue_key']}.", status_code=409)
        client = self.jira_client()
        try:
            created = client.create_issue({
                "project": {"key": project_key},
                "issuetype": {"name": issue_type},
                "summary": draft["summary"],
                "description": draft["description_adf"],
                "labels": draft["labels"],
            })
        finally:
            client.close()
        record = self.store.record_jira_ticket(
            analysis_id=analysis_id, finding_id=finding_id, project_key=project_key, issue_key=created["key"],
            issue_url=created["url"], summary=draft["summary"],
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return {**record, "jira_id": created.get("id")}

    def jira_issue_status(self, issue_key: str) -> dict[str, Any]:
        if not ISSUE_KEY_PATTERN.match(issue_key):
            raise InputError("Enter a valid Jira issue key, such as OPS-123.")
        client = self.jira_client()
        try:
            return client.issue_status(issue_key)
        finally:
            client.close()

    def jira_projects(self) -> list[dict[str, Any]]:
        client = self.jira_client()
        try:
            projects = client.projects()
            for project in projects:
                project["issue_types"] = client.issue_types(project["key"])
            return projects
        finally:
            client.close()


def _retrieval_query(question: str, history: list[dict[str, Any]]) -> str:
    last_user = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    if last_user and len(question.split()) < 6:
        return f"{last_user} {question}"
    return question


def _title_from(question: str) -> str:
    text = " ".join(question.split())
    return text[:60] + ("..." if len(text) > 60 else "")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
