from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.errors import NotFoundError
from app.ingestion import IngestionLimits
from app.pipeline import analyze_directory
from app.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    database = Store(tmp_path / "db" / "repomind.db")
    yield database
    database.close()


def _analysis(sample_dir: Path, analysis_id: str = "storeaid00001") -> dict:
    return analyze_directory(sample_dir, analysis_id=analysis_id, repository_name="sample", source_type="local",
                             source_ref="sample", limits=IngestionLimits())


def test_analysis_round_trips_through_sqlite(store: Store, sample_dir: Path):
    original = _analysis(sample_dir)
    store.save_analysis(original)
    loaded = store.load_analysis("storeaid00001")
    assert loaded["repository"] == "sample"
    assert len(loaded["files"]) == len(original["files"])
    assert len(loaded["symbols"]) == len(original["symbols"])
    assert len(loaded["edges"]) == len(original["edges"])
    assert len(loaded["findings"]) == len(original["findings"])
    assert len(loaded["chunks"]) == len(original["chunks"])
    assert loaded["summary"]["python_files"] == 11
    assert any(edge["confidence"] == "confirmed" for edge in loaded["edges"])


def test_metadata_listing_is_newest_first_and_reports_missing_ids(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir, "aaaaaaaaaaaa"))
    listing = store.list_analyses()
    assert listing[0]["analysis_id"] == "aaaaaaaaaaaa"
    with pytest.raises(NotFoundError):
        store.get_analysis_meta("bbbbbbbbbbbb")


def test_delete_cascades_to_child_tables(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir))
    store.set_report("storeaid00001", "/tmp/report.json", "2026-01-01T00:00:00+00:00")
    report_path = store.delete_analysis("storeaid00001")
    assert report_path == "/tmp/report.json"
    with pytest.raises(NotFoundError):
        store.load_analysis("storeaid00001")
    counts = store._connection.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert counts == 0


def test_duplicate_analysis_is_rejected_atomically(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir))
    with pytest.raises(Exception):
        store.save_analysis(_analysis(sample_dir))
    assert len(store.list_analyses()) == 1


def test_embeddings_round_trip_as_float32(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir))
    chunk_ids = [f"chunk-{i}" for i in range(3)]
    matrix = np.arange(12, dtype=np.float32).reshape(3, 4)
    store.save_analysis(_analysis(sample_dir, "embedaid0001"))
    store.save_embeddings("embedaid0001", "model-a", chunk_ids, matrix)
    loaded_ids, loaded = store.load_embeddings("embedaid0001", "model-a")
    assert loaded_ids == chunk_ids
    assert np.allclose(loaded, matrix)
    assert store.load_embeddings("embedaid0001", "other-model") is None


def test_ai_cache_stores_content_per_analysis(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir))
    store.put_cached("storeaid00001", "model|file:main.py", "cached text", "model", "2026-01-01T00:00:00+00:00")
    assert store.get_cached("storeaid00001", "model|file:main.py")["content"] == "cached text"
    assert store.get_cached("storeaid00001", "model|file:other.py") is None


def test_settings_are_stored_without_secrets(store: Store):
    assert store.get_settings() == {}
    store.update_settings({"graph_max_nodes": 200, "retrieval_mode": "hybrid"})
    store.update_settings({"graph_max_nodes": 120})
    assert store.get_settings() == {"graph_max_nodes": 120, "retrieval_mode": "hybrid"}


def test_jira_ticket_history_survives_analysis_deletion(store: Store, sample_dir: Path):
    store.save_analysis(_analysis(sample_dir))
    store.record_jira_ticket(analysis_id="storeaid00001", finding_id="RM-SEC-002-abc", project_key="OPS",
                             issue_key="OPS-12", issue_url="https://x.atlassian.net/browse/OPS-12",
                             summary="[RepoMind] test", created_at="2026-01-01T00:00:00+00:00")
    store.delete_analysis("storeaid00001")
    tickets = store.list_jira_tickets()
    assert tickets[0]["issue_key"] == "OPS-12"
    assert tickets[0]["analysis_id"] is None
