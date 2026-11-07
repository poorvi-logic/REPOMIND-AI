from pathlib import Path

from app.pipeline import analyze_repository


def test_ast_analysis_extracts_symbols_and_findings(tmp_path: Path):
    source = tmp_path / "example.py"
    source.write_text(
        "def helper(x):\n    print(x)\n\n"
        "def main():\n    try:\n        helper(None)\n"
        "    except:\n        return None\n",
        encoding="utf-8",
    )
    report = analyze_repository(tmp_path)
    assert report["summary"]["python_files"] == 1
    assert report["summary"]["functions"] == 2
    assert any(f["legacy_rule"] == "bare-except" for f in report["findings"])
    assert any(f["legacy_rule"] == "print-call" for f in report["findings"])
    assert any(e["target_name"] == "helper" for e in report["function_relationships"])


def test_syntax_error_is_reported(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def nope(:\n", encoding="utf-8")
    report = analyze_repository(tmp_path)
    assert report["summary"]["parse_errors"] == 1
