from __future__ import annotations

from app.dependencies import APPROXIMATE, CONFIRMED, EXTERNAL, UNRESOLVED, build_dependency_graph
from app.extractor import extract_structure, parse_source


def _file(path: str, source: str):
    tree, error = parse_source(source, path)
    assert error is None, error
    structure = extract_structure(tree, path)
    files = {
        "path": path, "module": structure["module"], "is_package": structure["is_package"],
        "imports": structure["imports"], "lines": source.count("\n") + 1,
    }
    scope = {"id": f"{path}::<module>", "file": path, "module": structure["module"], "qualname": "<module>",
             "name": "<module>", "kind": "module", "class_name": None, "is_nested": False,
             "calls": structure["module_calls"]}
    return files, structure["symbols"], scope


def _graph(*sources):
    files, symbols, scopes = [], [], []
    for path, source in sources:
        file_record, file_symbols, scope = _file(path, source)
        files.append(file_record)
        symbols.extend(file_symbols)
        scopes.append(scope)
    return build_dependency_graph(files, symbols, scopes)


def _call(graph, source_suffix, name):
    return next(edge for edge in graph["call_edges"]
                if edge["source"].endswith(source_suffix) and edge["target_name"].endswith(name))


PAYMENT = "def validate_payment(amount):\n    return amount > 0\n"
MAIN = (
    "from payment import validate_payment\n"
    "def checkout(amount):\n"
    "    return validate_payment(amount)\n"
)


def test_import_binding_creates_confirmed_edge_to_internal_function():
    graph = _graph(("payment.py", PAYMENT), ("main.py", MAIN))
    edge = _call(graph, "main.py::checkout", "validate_payment")
    assert edge["target"] == "payment.py::validate_payment"
    assert edge["resolution"] == "import"
    assert edge["confidence"] == CONFIRMED


def test_module_import_edges_are_confirmed_and_list_imported_names():
    graph = _graph(("payment.py", PAYMENT), ("main.py", MAIN))
    edge = graph["module_edges"][0]
    assert (edge["source"], edge["target"]) == ("main", "payment")
    assert edge["names"] == ["validate_payment"]
    assert edge["confidence"] == CONFIRMED


def test_same_module_and_nested_scope_resolution():
    source = (
        "def helper():\n    return 1\n"
        "def outer():\n"
        "    def inner():\n        return helper()\n"
        "    return inner()\n"
    )
    graph = _graph(("m.py", source))
    assert _call(graph, "m.py::outer.inner", "helper")["resolution"] == "same_module"
    assert _call(graph, "m.py::outer", "inner")["resolution"] == "enclosing_scope"


def test_self_method_calls_resolve_within_the_class():
    source = (
        "class Service:\n"
        "    def load(self):\n        return self.parse()\n"
        "    def parse(self):\n        return 1\n"
    )
    graph = _graph(("svc.py", source))
    edge = _call(graph, "svc.py::Service.load", "parse")
    assert edge["target"] == "svc.py::Service.parse"
    assert edge["resolution"] == "self_method"
    assert edge["confidence"] == CONFIRMED


def test_module_attribute_calls_are_confirmed():
    graph = _graph(("payment.py", PAYMENT),
                   ("main.py", "import payment\ndef run():\n    return payment.validate_payment(1)\n"))
    edge = _call(graph, "main.py::run", "validate_payment")
    assert edge["resolution"] == "module_attribute"
    assert edge["target"] == "payment.py::validate_payment"


def test_name_based_match_is_labelled_approximate():
    graph = _graph(
        ("store.py", "class Store:\n    def save_record(self):\n        return 1\n"),
        ("app.py", "def run(repo):\n    return repo.save_record()\n"),
    )
    edge = _call(graph, "app.py::run", "save_record")
    assert edge["confidence"] == APPROXIMATE
    assert edge["resolution"] == "name_match"
    assert edge["target"] == "store.py::Store.save_record"


def test_ambiguous_name_match_keeps_candidates_without_a_target():
    graph = _graph(
        ("a.py", "class A:\n    def process(self):\n        return 1\n"),
        ("b.py", "class B:\n    def process(self):\n        return 2\n"),
        ("c.py", "def run(obj):\n    return obj.process()\n"),
    )
    edge = _call(graph, "c.py::run", "process")
    assert edge["resolution"] == "name_match_ambiguous"
    assert edge["target"] is None
    assert len(edge["candidates"]) == 2


def test_external_and_builtin_calls_are_not_reported_as_unresolved():
    graph = _graph(("app.py", "import json\nfrom collections import Counter\n"
                              "def run(raw):\n    return json.loads(raw), Counter(), len(raw)\n"))
    assert _call(graph, "app.py::run", "json.loads")["confidence"] == EXTERNAL
    assert _call(graph, "app.py::run", "Counter")["confidence"] == EXTERNAL
    assert _call(graph, "app.py::run", "len")["resolution"] == "builtin"
    assert not any(item["name"] in {"json.loads", "len"} for item in graph["unresolved_references"])


def test_unknown_names_are_unresolved():
    graph = _graph(("app.py", "def run():\n    return mystery_function()\n"))
    edge = _call(graph, "app.py::run", "mystery_function")
    assert edge["confidence"] == UNRESOLVED
    assert graph["summary"]["unresolved_call_relationships"] >= 1


def test_class_members_are_recorded_as_contains_relationships():
    graph = _graph(("svc.py", "class Service:\n    def run(self):\n        return 1\n"))
    contains = graph["contains_edges"]
    assert any(edge["source"] == "svc.py::Service" and edge["target"] == "svc.py::Service.run" for edge in contains)


def test_module_cycle_is_detected_and_classified_by_import_timing():
    graph = _graph(
        ("alpha.py", "from beta import b_func\ndef a_func():\n    return b_func()\n"),
        ("beta.py", "from alpha import a_func\ndef b_func():\n    return a_func()\n"),
    )
    assert graph["summary"]["circular_dependencies"] == 1
    cycle = graph["cycles"][0]
    assert set(cycle["modules"]) == {"alpha", "beta"}
    assert cycle["runtime_risk"] == "module-level imports"
    assert cycle["example_cycle"][0] == cycle["example_cycle"][-1]

    lazy = _graph(
        ("alpha.py", "from beta import b_func\ndef a_func():\n    return b_func()\n"),
        ("beta.py", "def b_func():\n    from alpha import a_func\n    return a_func()\n"),
    )
    assert lazy["summary"]["circular_dependencies"] == 1
    assert lazy["cycles"][0]["runtime_risk"] == "includes function-level imports"


def test_external_dependencies_are_counted_by_top_level_package():
    graph = _graph(("app.py", "import yaml\nimport os.path\nfrom requests.adapters import HTTPAdapter\n"))
    assert graph["summary"]["external_modules"] == {"yaml": 1, "os": 1, "requests": 1}


def test_hub_modules_report_fan_in_and_fan_out():
    graph = _graph(
        ("core.py", "def core():\n    return 1\n"),
        ("a.py", "from core import core\n"),
        ("b.py", "from core import core\n"),
        ("c.py", "from core import core\n"),
    )
    hub = graph["summary"]["hub_modules"][0]
    assert hub["module"] == "core"
    assert hub["fan_in"] == 3
