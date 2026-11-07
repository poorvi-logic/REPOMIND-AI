from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_settings
from .index import RepositoryIndex
from .ingestion import IngestionLimits
from .pipeline import analyze_directory, new_analysis_id
from .reports import build_report

REPORTS_DIR = Path("reports")
LAST_PATH_FILE = REPORTS_DIR / "last_path.txt"


def _limits() -> IngestionLimits:
    settings = load_settings()
    return IngestionLimits(max_python_files=settings.max_python_files,
                           max_file_bytes=settings.max_file_kb * 1024,
                           max_repository_bytes=settings.max_repository_mb * 1024 * 1024)


def _analyze(path: Path) -> RepositoryIndex:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise SystemExit(f"Not a directory: {path}")
    analysis = analyze_directory(resolved, analysis_id=new_analysis_id(str(resolved)), repository_name=resolved.name,
                                 source_type="local", source_ref=resolved.name, limits=_limits())
    return RepositoryIndex(analysis)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RepoMind AI command-line tools")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Analyze a local repository directory")
    analyze.add_argument("path")
    search = commands.add_parser("search", help="Search the last analyzed repository or a given path")
    search.add_argument("query")
    search.add_argument("--path", default=None)
    args = parser.parse_args(argv)

    if args.command == "analyze":
        index = _analyze(Path(args.path))
        REPORTS_DIR.mkdir(exist_ok=True)
        report = build_report(index.analysis)
        (REPORTS_DIR / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        LAST_PATH_FILE.write_text(str(Path(args.path).expanduser().resolve()), encoding="utf-8")
        print(json.dumps(index.analysis["summary"], indent=2))
        return 0

    target = args.path
    if target is None:
        if not LAST_PATH_FILE.exists():
            print("No repository has been analyzed yet. Run: python -m app.cli analyze <path>", file=sys.stderr)
            return 1
        target = LAST_PATH_FILE.read_text(encoding="utf-8").strip()
    index = _analyze(Path(target))
    print(json.dumps(index.search(args.query, limit=8), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
