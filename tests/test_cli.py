from __future__ import annotations

import json
from pathlib import Path

from app import cli


def test_cli_analyze_and_search_round_trip(tmp_path, monkeypatch, sample_dir):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", str(sample_dir)]) == 0
    report = json.loads(Path("reports/latest.json").read_text(encoding="utf-8"))
    assert report["summary"]["python_files"] == 11
    assert cli.main(["search", "payment validation"]) == 0


def test_cli_search_without_prior_analysis_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["search", "anything"]) == 1
    assert "No repository" in capsys.readouterr().err
