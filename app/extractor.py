from __future__ import annotations

import ast
from typing import Any

MAX_TEXT = 160
_DEFINITION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_COMPOUND_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")
_PROPERTY_DECORATORS = {"property", "cached_property", "setter", "getter", "deleter"}


def parse_source(source: str, relative_path: str) -> tuple[ast.Module | None, dict[str, Any] | None]:
    try:
        return ast.parse(source, filename=relative_path), None
    except SyntaxError as exc:
        return None, {"message": exc.msg or "invalid syntax", "line": exc.lineno or 1}
    except (ValueError, RecursionError, MemoryError) as exc:
        return None, {"message": f"unable to parse file ({type(exc).__name__})", "line": 1}


def module_name_for(relative_path: str, package_roots: tuple[str, ...] = ()) -> str:
    path = relative_path
    for root in package_roots:
        prefix = root.rstrip("/") + "/"
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    without_suffix = path[:-3] if path.endswith(".py") else path
    parts = [part for part in without_suffix.split("/") if part]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or "__init__"


def is_package_file(relative_path: str) -> bool:
    return relative_path == "__init__.py" or relative_path.endswith("/__init__.py")


def expression_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{expression_text(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{expression_text(node.func)}(...)"
    if isinstance(node, ast.Subscript):
        return f"{expression_text(node.value)}[...]"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "<str>"
    return "<expr>"


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    text = ast.unparse(node)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 3] + "..."


def _describe_call(call: ast.Call) -> dict[str, Any]:
    func = call.func
    line = getattr(call, "lineno", 0)
    if isinstance(func, ast.Name):
        return {"name": func.id, "receiver": None, "kind": "name", "text": func.id, "line": line}
    if isinstance(func, ast.Attribute):
        receiver = expression_text(func.value)
        return {"name": func.attr, "receiver": receiver, "kind": "attribute", "text": f"{receiver}.{func.attr}", "line": line}
    return {"name": "<dynamic>", "receiver": None, "kind": "dynamic", "text": expression_text(func), "line": line}


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(_describe_call(node))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.AST) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)


class _ComplexityCounter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.score = 1

    def visit_If(self, node: ast.If) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.score += 1
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.score += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.score += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_match_case(self, node: ast.AST) -> None:
        self.score += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.AST) -> None:
        return None

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef


def _definitions_in(statements: list[ast.stmt]):
    for statement in statements:
        if isinstance(statement, _DEFINITION_TYPES):
            yield statement
            continue
        for field_name in _COMPOUND_FIELDS:
            children = getattr(statement, field_name, None)
            if isinstance(children, list):
                yield from _definitions_in(children)


def _collect_calls(statements: list[ast.stmt]) -> list[dict[str, Any]]:
    collector = _CallCollector()
    for statement in statements:
        collector.visit(statement)
    return collector.calls


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    return expression_text(target)


def _method_type(decorators: list[str]) -> str:
    if "staticmethod" in decorators:
        return "staticmethod"
    if "classmethod" in decorators:
        return "classmethod"
    if any(name.split(".")[-1] in _PROPERTY_DECORATORS for name in decorators):
        return "property"
    return "instance"


def _argument_entry(name: str, annotation: ast.expr | None, has_default: bool, kind: str) -> dict[str, Any]:
    return {"name": name, "annotation": _unparse(annotation), "default": has_default, "kind": kind}


def _arguments(arguments: ast.arguments) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    positional = [*arguments.posonlyargs, *arguments.args]
    first_default = len(positional) - len(arguments.defaults)
    for index, argument in enumerate(positional):
        entries.append(_argument_entry(argument.arg, argument.annotation, index >= first_default, "positional"))
    if arguments.vararg:
        entries.append(_argument_entry(f"*{arguments.vararg.arg}", arguments.vararg.annotation, False, "vararg"))
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        entries.append(_argument_entry(argument.arg, argument.annotation, default is not None, "keyword_only"))
    if arguments.kwarg:
        entries.append(_argument_entry(f"**{arguments.kwarg.arg}", arguments.kwarg.annotation, False, "kwarg"))
    return entries


def _first_docstring_line(node: ast.AST) -> str | None:
    docstring = ast.get_docstring(node, clean=True)
    if not docstring:
        return None
    first = next((line.strip() for line in docstring.splitlines() if line.strip()), "")
    return first[:200] or None


def _start_line(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", [])
    return min([node.lineno, *[item.lineno for item in decorators]])


def _symbol_base(relative_path: str, module: str, node: ast.AST, qualname: str, kind: str,
                 class_name: str | None, is_nested: bool) -> dict[str, Any]:
    end_line = getattr(node, "end_lineno", None) or node.lineno
    return {
        "id": f"{relative_path}::{qualname}",
        "file": relative_path,
        "module": module,
        "name": node.name,
        "qualname": qualname,
        "kind": kind,
        "class_name": class_name,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "is_nested": is_nested,
        "line": node.lineno,
        "start_line": _start_line(node),
        "end_line": end_line,
        "length": end_line - node.lineno + 1,
        "decorators": [_decorator_name(item) for item in node.decorator_list],
        "docstring": _first_docstring_line(node),
    }


def _function_symbol(node: ast.AST, relative_path: str, module: str, qualname: str,
                     class_name: str | None, is_nested: bool, in_class: bool) -> dict[str, Any]:
    kind = "method" if in_class else ("nested_function" if is_nested else "function")
    symbol = _symbol_base(relative_path, module, node, qualname, kind, class_name, is_nested)
    symbol["method_type"] = _method_type(symbol["decorators"]) if in_class else None
    symbol["arguments"] = _arguments(node.args)
    symbol["returns"] = _unparse(node.returns)
    symbol["bases"] = []
    symbol["calls"] = _collect_calls(node.body)
    counter = _ComplexityCounter()
    for statement in node.body:
        counter.visit(statement)
    symbol["complexity"] = counter.score
    return symbol


def _class_symbol(node: ast.ClassDef, relative_path: str, module: str, qualname: str,
                  class_name: str | None, is_nested: bool) -> dict[str, Any]:
    symbol = _symbol_base(relative_path, module, node, qualname, "class", class_name, is_nested)
    symbol["method_type"] = None
    symbol["arguments"] = []
    symbol["returns"] = None
    symbol["bases"] = [_unparse(base) for base in node.bases]
    symbol["calls"] = _collect_calls(node.body)
    symbol["complexity"] = 1
    return symbol


def _collect_definitions(statements: list[ast.stmt], relative_path: str, module: str, scope: str,
                         owner: str, class_name: str | None, symbols: list[dict[str, Any]]) -> None:
    for node in _definitions_in(statements):
        qualname = f"{scope}.{node.name}" if scope else node.name
        if isinstance(node, ast.ClassDef):
            symbols.append(_class_symbol(node, relative_path, module, qualname,
                                         class_name if owner != "module" else None, owner == "function"))
            _collect_definitions(node.body, relative_path, module, qualname, "class", qualname, symbols)
        else:
            symbols.append(_function_symbol(node, relative_path, module, qualname, class_name,
                                            is_nested=owner == "function", in_class=owner == "class"))
            _collect_definitions(node.body, relative_path, module, qualname, "function", class_name, symbols)


def _collect_imports(node: ast.AST, lazy: bool, records: list[dict[str, Any]]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                records.append({
                    "kind": "import", "module": alias.name, "symbol": None,
                    "local": alias.asname or alias.name.split(".")[0],
                    "target": alias.name if alias.asname else alias.name.split(".")[0],
                    "level": 0, "line": child.lineno, "lazy": lazy,
                })
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                records.append({
                    "kind": "from", "module": child.module or "", "symbol": alias.name,
                    "local": alias.asname or alias.name, "target": None,
                    "level": child.level, "line": child.lineno, "lazy": lazy,
                })
        else:
            _collect_imports(child, lazy or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)), records)


def _ensure_unique_symbol_ids(symbols: list[dict[str, Any]]) -> None:
    from collections import Counter

    counts = Counter((item["file"], item["qualname"]) for item in symbols)
    used: set[str] = set()
    for item in symbols:
        if counts[(item["file"], item["qualname"])] > 1:
            candidate = f"{item['file']}::{item['qualname']}@{item['line']}"
            suffix = 2
            while candidate in used:
                candidate = f"{item['file']}::{item['qualname']}@{item['line']}#{suffix}"
                suffix += 1
            item["id"] = candidate
        used.add(item["id"])


def extract_structure(tree: ast.Module, relative_path: str, package_roots: tuple[str, ...] = ()) -> dict[str, Any]:
    module = module_name_for(relative_path, package_roots)
    symbols: list[dict[str, Any]] = []
    _collect_definitions(tree.body, relative_path, module, "", "module", None, symbols)
    _ensure_unique_symbol_ids(symbols)
    imports: list[dict[str, Any]] = []
    _collect_imports(tree, False, imports)
    return {
        "module": module,
        "is_package": is_package_file(relative_path),
        "imports": imports,
        "symbols": symbols,
        "module_calls": _collect_calls(tree.body),
    }
