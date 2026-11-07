from __future__ import annotations

from app.dependencies import resolve_import_module
from app.extractor import extract_structure, module_name_for, parse_source

SOURCE = '''
import os
from pkg import helper as h
from . import sibling
from typing import Optional


class Repo:
    """Repository access."""

    @property
    def size(self) -> int:
        return len(self.items)

    @classmethod
    def build(cls, *args, flag: bool = False, **kw):
        return cls()

    async def fetch(self, key: str, limit=10):
        def inner(x):
            return helper(x)
        return inner(key)


def top(a, b=2):
    if a and b:
        return h(a)
    return [x for x in range(3) if x]


if __name__ == "__main__":
    top(1)
'''


def _structure(source: str = SOURCE, path: str = "pkg/x.py"):
    tree, error = parse_source(source, path)
    assert error is None
    return extract_structure(tree, path)


def _symbol(structure, qualname):
    return next(item for item in structure["symbols"] if item["qualname"] == qualname)


def test_classes_methods_and_nested_functions_keep_context():
    structure = _structure()
    kinds = {item["qualname"]: item["kind"] for item in structure["symbols"]}
    assert kinds["Repo"] == "class"
    assert kinds["Repo.size"] == "method"
    assert kinds["Repo.fetch.inner"] == "nested_function"
    assert kinds["top"] == "function"
    assert _symbol(structure, "Repo.fetch.inner")["is_nested"] is True
    assert _symbol(structure, "Repo.fetch")["class_name"] == "Repo"
    assert _symbol(structure, "Repo")["docstring"] == "Repository access."


def test_async_decorators_and_method_types():
    structure = _structure()
    fetch = _symbol(structure, "Repo.fetch")
    assert fetch["is_async"] is True
    assert _symbol(structure, "Repo.size")["method_type"] == "property"
    assert _symbol(structure, "Repo.size")["decorators"] == ["property"]
    assert _symbol(structure, "Repo.build")["method_type"] == "classmethod"


def test_arguments_annotations_defaults_and_return_types():
    structure = _structure()
    top = _symbol(structure, "top")
    assert [arg["name"] for arg in top["arguments"]] == ["a", "b"]
    assert [arg["default"] for arg in top["arguments"]] == [False, True]
    build = _symbol(structure, "Repo.build")
    kinds = {arg["name"]: arg["kind"] for arg in build["arguments"]}
    assert kinds == {"cls": "positional", "*args": "vararg", "flag": "keyword_only", "**kw": "kwarg"}
    size = _symbol(structure, "Repo.size")
    assert size["returns"] == "int"


def test_calls_are_attributed_to_their_own_function_only():
    structure = _structure()
    fetch_calls = {call["text"] for call in _symbol(structure, "Repo.fetch")["calls"]}
    assert "inner" in fetch_calls
    assert "helper" not in fetch_calls
    inner_calls = {call["text"] for call in _symbol(structure, "Repo.fetch.inner")["calls"]}
    assert inner_calls == {"helper"}
    assert {call["text"] for call in structure["module_calls"]} == {"top"}


def test_line_numbers_and_lengths_are_recorded():
    structure = _structure()
    top = _symbol(structure, "top")
    assert top["line"] == 25
    assert top["end_line"] == 28
    assert top["length"] == 4


def test_imports_record_relative_levels_aliases_and_lazy_flags():
    structure = _structure("import os\nfrom . import sibling\nfrom pkg import helper as h\n"
                           "def f():\n    import json\n", "pkg/mod.py")
    by_local = {item["local"]: item for item in structure["imports"]}
    assert by_local["os"]["module"] == "os"
    assert by_local["sibling"]["level"] == 1
    assert by_local["h"]["symbol"] == "helper"
    assert by_local["json"]["lazy"] is True
    assert by_local["os"]["lazy"] is False


def test_module_names_and_package_detection():
    assert module_name_for("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name_for("pkg/__init__.py") == "pkg"
    assert module_name_for("main.py") == "main"


def test_relative_import_resolution():
    assert resolve_import_module("pkg.mod", False, 1, "sibling") == "pkg.sibling"
    assert resolve_import_module("pkg.mod", False, 1, "") == "pkg"
    assert resolve_import_module("pkg", True, 1, "x") == "pkg.x"
    assert resolve_import_module("pkg.sub.mod", False, 2, "other") == "pkg.other"
    assert resolve_import_module("top", False, 3, "x") is None
    assert resolve_import_module("", False, 0, "os.path") == "os.path"


def test_syntax_errors_are_reported_with_line():
    tree, error = parse_source("def broken(:\n    pass\n", "broken.py")
    assert tree is None
    assert error["line"] == 1
    assert error["message"]


def test_cyclomatic_complexity_counts_branches():
    structure = _structure()
    assert _symbol(structure, "top")["complexity"] == 5
    assert _symbol(structure, "Repo.size")["complexity"] == 1


def test_property_setter_pairs_get_unique_symbol_ids():
    source = (
        "class Account:\n"
        "    @property\n"
        "    def balance(self):\n"
        "        return self._balance\n"
        "    @balance.setter\n"
        "    def balance(self, value):\n"
        "        self._balance = value\n"
    )
    structure = _structure(source, "bank/account.py")
    ids = [item["id"] for item in structure["symbols"] if item["name"] == "balance"]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(item.startswith("bank/account.py::Account.balance@") for item in ids)


def test_conditional_redefinitions_remain_unique():
    source = (
        "try:\n    from fast import parse\nexcept ImportError:\n"
        "    def parse(text):\n        return text\n"
        "else:\n    def parse(text):\n        return text.strip()\n"
    )
    structure = _structure(source, "parsing.py")
    ids = [item["id"] for item in structure["symbols"] if item["qualname"] == "parse"]
    assert len(ids) == 2 and len(set(ids)) == 2
