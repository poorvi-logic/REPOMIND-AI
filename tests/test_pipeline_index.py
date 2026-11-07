from __future__ import annotations

import pytest

from app.errors import NotFoundError
from app.index import RepositoryIndex
from app.ingestion import IngestionLimits
from app.pipeline import analyze_directory, analyze_repository


@pytest.fixture(scope="module")
def sample_index(sample_dir):
    analysis = analyze_directory(
        sample_dir, analysis_id="sampleindex01", repository_name="sample", source_type="local",
        source_ref="sample", limits=IngestionLimits(),
    )
    return RepositoryIndex(analysis)


def test_summary_reflects_the_sample_repository(sample_index):
    summary = sample_index.analysis["summary"]
    assert summary["python_files"] == 11
    assert summary["classes"] >= 4
    assert summary["methods"] >= 5
    assert summary["parse_errors"] == 0
    assert summary["circular_dependencies"] == 1
    assert summary["findings"] >= 8


def test_sample_findings_cover_the_seeded_risk_patterns(sample_index):
    rules = {item["rule_id"] for item in sample_index.findings.values()}
    assert {"RM-SEC-001", "RM-SEC-002", "RM-SEC-004", "RM-ERR-001", "RM-SQL-001", "RM-QUAL-001"} <= rules
    token = next(item for item in sample_index.findings.values() if item["rule_id"] == "RM-SEC-001")
    assert "demo-token-0123456789abcdef" not in token["evidence"]


def test_cycle_between_orders_and_notifications_is_reported_with_timing(sample_index):
    cycle = sample_index.cycles[0]
    assert set(cycle["modules"]) == {"orders", "notifications"}
    assert cycle["runtime_risk"] == "includes function-level imports"


def test_symbol_detail_includes_confirmed_callers_and_callees(sample_index):
    detail = sample_index.symbol_detail("main.py::checkout")
    callee = next(item for item in detail["callees"] if item["target"] == "payment.py::validate_payment")
    assert callee["confidence"] == "confirmed"
    assert callee["resolution"] == "import"
    caller_names = {item["source_name"] for item in sample_index.symbol_detail("payment.py::validate_payment")["callers"]}
    assert "checkout" in caller_names


def test_class_detail_lists_its_methods(sample_index):
    detail = sample_index.symbol_detail("orders.py::OrderService")
    assert "orders.py::OrderService.create_order" in detail["members"]


def test_async_method_is_recorded_as_async(sample_index):
    detail = sample_index.symbol_detail("orders.py::OrderService.refund")
    assert detail["is_async"] is True
    assert detail["callees"][0]["target"] == "orders.py::OrderService.get"


def test_name_based_method_call_is_approximate(sample_index):
    detail = sample_index.symbol_detail("api.py::refund_order")
    refund_call = next(item for item in detail["callees"] if item["target_name"].endswith("refund"))
    assert refund_call["confidence"] == "approximate"


def test_missing_symbol_and_file_raise_not_found(sample_index):
    with pytest.raises(NotFoundError):
        sample_index.symbol_detail("nope.py::missing")
    with pytest.raises(NotFoundError):
        sample_index.file_detail("missing.py")
    with pytest.raises(NotFoundError):
        sample_index.finding("RM-XXX-000")


def test_file_detail_reports_imports_classes_and_module_links(sample_index):
    detail = sample_index.file_detail("orders.py")
    assert {item["name"] for item in detail["classes"]} == {"Order", "OrderService"}
    assert any(item["module"] == "notifications" for item in detail["module_dependencies"]["imports"])
    importers = {item["module"] for item in detail["module_dependencies"]["imported_by"]}
    assert importers == {"main", "api", "notifications"}


def test_list_symbols_filters_and_excludes_module_scopes(sample_index):
    results = sample_index.list_symbols(query="refund")
    assert results and all("refund" in item["qualname"].lower() or "refund" in item["file"].lower() for item in results)
    assert all(item["kind"] != "module" for item in sample_index.list_symbols(limit=1000))


def test_dependency_graph_modes_and_filters(sample_index):
    modules = sample_index.dependency_graph("modules")
    assert any(node["id"] == "orders" for node in modules["nodes"])
    assert any(node["in_cycle"] for node in modules["nodes"])
    confirmed = sample_index.dependency_graph("functions", confidence="confirmed")
    everything = sample_index.dependency_graph("functions", confidence="all")
    assert everything["total_edges"] >= confirmed["total_edges"]
    assert all(edge["confidence"] == "confirmed" for edge in confirmed["edges"])


def test_dependency_graph_focus_and_node_limit(sample_index):
    focused = sample_index.dependency_graph("functions", confidence="all", focus="payment.py::validate_payment")
    assert focused["nodes"]
    limited = sample_index.dependency_graph("functions", confidence="all", max_nodes=10)
    assert len(limited["nodes"]) <= 10


def test_risk_filters_by_severity_rule_and_file(sample_index):
    high = sample_index.risks("high")
    assert high and all(item["severity"] == "high" for item in high)
    by_rule = sample_index.risks("info", rule_id="RM-ERR-001")
    assert by_rule and all(item["rule_id"] == "RM-ERR-001" for item in by_rule)
    by_file = sample_index.risks("info", file="reports.py")
    assert by_file and all(item["file"] == "reports.py" for item in by_file)


def test_call_flow_follows_confirmed_edges_and_marks_recursion(sample_index):
    flow = sample_index.call_flow("main.py::main", depth=3)
    assert flow["tree"]["children"][0]["name"] == "checkout"
    assert any("validate_payment" in line for line in flow["lines"])


def test_graph_facts_mention_matching_symbols_and_modules(sample_index):
    facts = sample_index.graph_facts("which modules depend on notifications and who calls validate_payment?")
    assert any("validate_payment is defined in payment.py" in fact for fact in facts)
    assert any("Module notifications" in fact for fact in facts)


def test_search_finds_the_payment_validation_code(sample_index):
    hits = sample_index.search("payment validation", limit=3)
    assert hits[0]["file"] == "payment.py"


def test_analyze_repository_compat_wrapper_still_works(sample_dir):
    report = analyze_repository(sample_dir, max_files=50)
    assert report["summary"]["python_files"] == 11
    assert report["function_relationships"]
    assert report["findings"]


def test_source_snippet_is_bounded_for_large_symbols(tmp_path):
    body = "\n".join(f"    value_{i} = {i}" for i in range(450))
    (tmp_path / "big.py").write_text(f"def huge():\n{body}\n", encoding="utf-8")
    analysis = analyze_directory(tmp_path, analysis_id="bigindex0001", repository_name="big", source_type="local",
                                 source_ref="big", limits=IngestionLimits())
    detail = RepositoryIndex(analysis).symbol_detail("big.py::huge")
    assert detail["source"]["truncated"] is True
    assert detail["source"]["text"].count("\n") < 401


def test_repository_with_property_setters_analyzes_and_persists(tmp_path):
    from app.store import Store

    (tmp_path / "model.py").write_text(
        "class Thing:\n    @property\n    def size(self):\n        return self._size\n"
        "    @size.setter\n    def size(self, value):\n        self._size = value\n",
        encoding="utf-8",
    )
    analysis = analyze_directory(tmp_path, analysis_id="propertyaid01", repository_name="props",
                                 source_type="local", source_ref="props", limits=IngestionLimits())
    store = Store(tmp_path / "db.sqlite")
    store.save_analysis(analysis)
    loaded = store.load_analysis("propertyaid01")
    assert len([item for item in loaded["symbols"] if item["name"] == "size"]) == 2
    store.close()


def test_src_layout_packages_resolve_as_internal_modules(tmp_path):
    (tmp_path / "src" / "shop").mkdir(parents=True)
    (tmp_path / "src" / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "shop" / "core.py").write_text(
        "from shop.util import helper\n\ndef run():\n    return helper()\n", encoding="utf-8")
    (tmp_path / "src" / "shop" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("from shop.core import run\n", encoding="utf-8")
    analysis = analyze_directory(tmp_path, analysis_id="srclayoutaid1", repository_name="shop",
                                 source_type="local", source_ref="shop", limits=IngestionLimits())
    modules = {file["module"] for file in analysis["files"]}
    assert {"shop.core", "shop.util", "shop"} <= modules
    edges = {(edge["source"], edge["target"]) for edge in analysis["edges"] if edge["kind"] == "module_import"}
    assert ("shop.core", "shop.util") in edges
    assert "shop" not in analysis["dependency_summary"]["external_modules"]
    run_call = next(edge for edge in analysis["edges"] if edge["kind"] == "calls" and edge["target_name"] == "helper")
    assert run_call["confidence"] == "confirmed"
