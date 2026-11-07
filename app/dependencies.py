from __future__ import annotations

import builtins
from collections import Counter, defaultdict
from typing import Any

CONFIRMED = "confirmed"
APPROXIMATE = "approximate"
EXTERNAL = "external"
UNRESOLVED = "unresolved"
MAX_CANDIDATES = 5
MAX_UNRESOLVED_REPORTED = 150
BUILTIN_NAMES = frozenset(dir(builtins))
SELF_NAMES = frozenset({"self", "cls"})
CALLABLE_KINDS = frozenset({"function", "method", "nested_function"})


def resolve_import_module(current_module: str, is_package: bool, level: int, target: str) -> str | None:
    if level == 0:
        return target or None
    parts = current_module.split(".") if current_module else []
    package_parts = parts if is_package else parts[:-1]
    ascend = level - 1
    if ascend > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - ascend]
    combined = base + (target.split(".") if target else [])
    return ".".join(combined) or None


class _SymbolIndex:
    def __init__(self, symbols: list[dict[str, Any]], module_to_file: dict[str, str]) -> None:
        self.module_to_file = module_to_file
        self.by_file_qualname: dict[tuple[str, str], dict[str, Any]] = {}
        self.top_level_by_module: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.methods_by_class: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        self.callables_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for symbol in symbols:
            self.by_file_qualname[(symbol["file"], symbol["qualname"])] = symbol
            if symbol["class_name"] is None and not symbol["is_nested"]:
                self.top_level_by_module[symbol["module"]][symbol["name"]] = symbol
            if symbol["kind"] == "method" and symbol["class_name"]:
                self.methods_by_class[(symbol["file"], symbol["class_name"])][symbol["name"]] = symbol
            if symbol["kind"] in CALLABLE_KINDS:
                self.callables_by_name[symbol["name"]].append(symbol)

    def kind_of(self, file_path: str, qualname: str) -> str | None:
        found = self.by_file_qualname.get((file_path, qualname))
        return found["kind"] if found else None

    def longest_internal_module(self, dotted: str) -> str | None:
        parts = dotted.split(".") if dotted else []
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self.module_to_file:
                return candidate
        return None


def _bindings_for(file_record: dict[str, Any], index: _SymbolIndex) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    is_package = file_record["is_package"]
    current_module = file_record["module"]
    for record in file_record["imports"]:
        if record["kind"] == "import":
            target = record["target"]
            bindings[record["local"]] = {
                "type": "module", "module": target, "internal": target in index.module_to_file,
            }
            continue
        if record["symbol"] == "*":
            continue
        resolved = resolve_import_module(current_module, is_package, record["level"], record["module"])
        candidate = f"{resolved}.{record['symbol']}" if resolved else record["symbol"]
        if candidate in index.module_to_file:
            bindings[record["local"]] = {"type": "module", "module": candidate, "internal": True}
        elif resolved and resolved in index.module_to_file:
            bindings[record["local"]] = {
                "type": "symbol", "module": resolved, "symbol": record["symbol"], "internal": True,
            }
        else:
            bindings[record["local"]] = {
                "type": "symbol", "module": resolved or "", "symbol": record["symbol"], "internal": False,
            }
    return bindings


def _module_edges(files: list[dict[str, Any]], index: _SymbolIndex) -> tuple[list[dict[str, Any]], Counter]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    external: Counter = Counter()
    for file_record in files:
        source_module = file_record["module"]
        for record in file_record["imports"]:
            if record["kind"] == "import":
                full_name = record["module"]
                internal_target = index.longest_internal_module(full_name)
                if internal_target is None:
                    external[full_name.split(".")[0]] += 1
                    continue
                target_module = internal_target
                symbol_name = None
            else:
                if record["symbol"] == "*":
                    continue
                resolved = resolve_import_module(source_module, file_record["is_package"], record["level"], record["module"])
                if resolved is None:
                    continue
                submodule = f"{resolved}.{record['symbol']}"
                if submodule in index.module_to_file:
                    target_module = submodule
                    symbol_name = None
                else:
                    internal_target = index.longest_internal_module(resolved)
                    if internal_target is None:
                        external[resolved.split(".")[0]] += 1
                        continue
                    target_module = internal_target
                    symbol_name = record["symbol"]
            if target_module == source_module:
                continue
            key = (source_module, target_module)
            entry = grouped.setdefault(key, {
                "kind": "module_import", "source": source_module, "target": target_module,
                "names": set(), "line": record["line"], "lazy": True, "confidence": CONFIRMED,
                "source_file": file_record["path"],
            })
            if symbol_name:
                entry["names"].add(symbol_name)
            entry["line"] = min(entry["line"], record["line"])
            entry["lazy"] = entry["lazy"] and record["lazy"]
    edges = []
    for entry in grouped.values():
        entry["names"] = sorted(entry["names"])
        edges.append(entry)
    edges.sort(key=lambda item: (item["source"], item["target"]))
    return edges, external


def _lookup_bare_name(index: _SymbolIndex, file_path: str, caller_qualname: str, name: str) -> dict[str, Any] | None:
    parts = caller_qualname.split(".") if caller_qualname else []
    for depth in range(len(parts), -1, -1):
        prefix = parts[:depth]
        if prefix and index.kind_of(file_path, ".".join(prefix)) == "class":
            continue
        qualname = ".".join([*prefix, name])
        candidate = index.by_file_qualname.get((file_path, qualname))
        if candidate and candidate["kind"] != "method":
            return candidate
    return None


def _edge(caller_id: str, call: dict[str, Any], target: dict[str, Any] | None, target_name: str,
          resolution: str, confidence: str, candidates: list[str] | None = None) -> dict[str, Any]:
    return {
        "kind": "calls", "source": caller_id, "target": target["id"] if target else None,
        "target_name": target_name, "line": call["line"], "resolution": resolution,
        "confidence": confidence, "candidates": candidates or [],
    }


def _resolve_name_call(index, file_path, bindings, caller, call) -> dict[str, Any]:
    name = call["name"]
    caller_id = caller["id"]
    local = _lookup_bare_name(index, file_path, caller["qualname"], name)
    if local:
        resolution = "same_module" if "." not in local["qualname"] else "enclosing_scope"
        return _edge(caller_id, call, local, name, resolution, CONFIRMED)
    binding = bindings.get(name)
    if binding and binding["type"] == "symbol":
        if binding["internal"]:
            target = index.top_level_by_module.get(binding["module"], {}).get(binding["symbol"])
            if target:
                return _edge(caller_id, call, target, name, "import", CONFIRMED)
            return _edge(caller_id, call, None, f"{binding['module']}.{binding['symbol']}",
                         "import_unresolved", UNRESOLVED)
        return _edge(caller_id, call, None, f"{binding['module']}.{binding['symbol']}",
                     "external_import", EXTERNAL)
    if binding and binding["type"] == "module":
        return _edge(caller_id, call, None, name, "module_call", UNRESOLVED)
    if name in BUILTIN_NAMES:
        return _edge(caller_id, call, None, name, "builtin", EXTERNAL)
    return _edge(caller_id, call, None, name, "unknown_name", UNRESOLVED)


def _resolve_attribute_call(index, file_path, bindings, caller, call) -> dict[str, Any]:
    name = call["name"]
    receiver = call.get("receiver") or ""
    caller_id = caller["id"]
    class_name = caller.get("class_name")
    if receiver in SELF_NAMES and class_name:
        method = index.methods_by_class.get((file_path, class_name), {}).get(name)
        if method:
            return _edge(caller_id, call, method, call["text"], "self_method", CONFIRMED)
    head, _, remainder = receiver.partition(".")
    binding = bindings.get(head) if head else None
    if binding and binding["type"] == "module":
        module_path = f"{binding['module']}.{remainder}" if remainder else binding["module"]
        target_module = module_path if module_path in index.module_to_file else binding["module"]
        if binding["internal"] or target_module in index.module_to_file:
            target = index.top_level_by_module.get(target_module, {}).get(name)
            if target:
                return _edge(caller_id, call, target, call["text"], "module_attribute", CONFIRMED)
            return _edge(caller_id, call, None, call["text"], "module_attribute_unresolved", UNRESOLVED)
        return _edge(caller_id, call, None, call["text"], "external_import", EXTERNAL)
    if binding and binding["type"] == "symbol":
        if not binding["internal"]:
            return _edge(caller_id, call, None, call["text"], "external_import", EXTERNAL)
        class_symbol = index.top_level_by_module.get(binding["module"], {}).get(binding["symbol"])
        if class_symbol and class_symbol["kind"] == "class" and not remainder:
            method = index.methods_by_class.get((class_symbol["file"], class_symbol["qualname"]), {}).get(name)
            if method:
                return _edge(caller_id, call, method, call["text"], "class_attribute", CONFIRMED)
    matches = index.callables_by_name.get(name, [])
    if len(matches) == 1:
        return _edge(caller_id, call, matches[0], call["text"], "name_match", APPROXIMATE)
    if len(matches) > 1:
        candidate_ids = [item["id"] for item in matches[:MAX_CANDIDATES]]
        return _edge(caller_id, call, None, call["text"], "name_match_ambiguous", APPROXIMATE, candidate_ids)
    return _edge(caller_id, call, None, call["text"], "no_internal_match", UNRESOLVED)


def _resolve_call(index, file_path, bindings, caller, call) -> dict[str, Any]:
    if call["kind"] == "name":
        return _resolve_name_call(index, file_path, bindings, caller, call)
    if call["kind"] == "attribute":
        return _resolve_attribute_call(index, file_path, bindings, caller, call)
    return _edge(caller["id"], call, None, call["text"], "dynamic_call", UNRESOLVED)


def _strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def connect(node: str) -> None:
        indices[node] = lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for neighbour in graph.get(node, ()):
            if neighbour not in indices:
                connect(neighbour)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbour])
            elif neighbour in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbour])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            connect(node)
    return components


def _representative_cycle(component: list[str], graph: dict[str, set[str]]) -> list[str]:
    members = set(component)
    start = component[0]
    parents: dict[str, str | None] = {start: None}
    frontier = [start]
    while frontier:
        next_frontier = []
        for node in frontier:
            for neighbour in sorted(graph.get(node, ())):
                if neighbour not in members:
                    continue
                if neighbour == start and node != start:
                    path = [node]
                    current = parents[node]
                    while current is not None:
                        path.append(current)
                        current = parents[current]
                    path.reverse()
                    return [*path, start]
                if neighbour not in parents:
                    parents[neighbour] = node
                    next_frontier.append(neighbour)
        frontier = next_frontier
    return [start, start]


def _module_cycles(module_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graph: dict[str, set[str]] = defaultdict(set)
    lazy_flags: dict[tuple[str, str], bool] = {}
    for edge in module_edges:
        graph[edge["source"]].add(edge["target"])
        lazy_flags[(edge["source"], edge["target"])] = edge["lazy"]
    cycles = []
    for component in _strongly_connected(graph):
        if len(component) == 1 and component[0] not in graph.get(component[0], ()):
            continue
        path = _representative_cycle(component, graph)
        pairs = list(zip(path, path[1:]))
        module_level = all(not lazy_flags.get(pair, True) for pair in pairs)
        cycles.append({
            "modules": component,
            "example_cycle": path,
            "runtime_risk": "module-level imports" if module_level else "includes function-level imports",
            "note": "Derived from static import statements. Cycles can cause ImportError at import time.",
        })
    cycles.sort(key=lambda item: (-len(item["modules"]), item["modules"]))
    return cycles


def build_dependency_graph(files: list[dict[str, Any]], symbols: list[dict[str, Any]],
                           module_scopes: list[dict[str, Any]]) -> dict[str, Any]:
    module_to_file: dict[str, str] = {}
    for file_record in files:
        module_to_file.setdefault(file_record["module"], file_record["path"])
    index = _SymbolIndex(symbols + module_scopes, module_to_file)
    module_edges, external_counter = _module_edges(files, index)

    bindings_by_file = {record["path"]: _bindings_for(record, index) for record in files}
    call_edges: list[dict[str, Any]] = []
    contains_edges: list[dict[str, Any]] = []
    for symbol in symbols:
        bindings = bindings_by_file.get(symbol["file"], {})
        for call in symbol["calls"]:
            call_edges.append(_resolve_call(index, symbol["file"], bindings, symbol, call))
        parent_qualname = symbol["qualname"].rsplit(".", 1)[0] if "." in symbol["qualname"] else None
        parent = index.by_file_qualname.get((symbol["file"], parent_qualname)) if parent_qualname else None
        if parent and parent["kind"] in {"class", "function", "method", "nested_function"}:
            contains_edges.append({
                "kind": "contains", "source": parent["id"], "target": symbol["id"], "target_name": symbol["name"],
                "line": symbol["line"], "resolution": "class_member" if symbol["kind"] == "method" else "nested_definition",
                "confidence": CONFIRMED, "candidates": [],
            })
    for scope in module_scopes:
        bindings = bindings_by_file.get(scope["file"], {})
        for call in scope["calls"]:
            call_edges.append(_resolve_call(index, scope["file"], bindings, scope, call))

    cycles = _module_cycles(module_edges)
    confidence_counts = Counter(edge["confidence"] for edge in call_edges)
    unresolved_groups: dict[str, dict[str, Any]] = {}
    for edge in call_edges:
        if edge["confidence"] != UNRESOLVED:
            continue
        group = unresolved_groups.setdefault(edge["target_name"], {
            "name": edge["target_name"], "resolution": edge["resolution"], "count": 0, "locations": [],
        })
        group["count"] += 1
        if len(group["locations"]) < 3:
            group["locations"].append({"source": edge["source"], "line": edge["line"]})
    unresolved = sorted(unresolved_groups.values(), key=lambda item: (-item["count"], item["name"]))
    fan_in: Counter = Counter()
    fan_out: Counter = Counter()
    for edge in module_edges:
        fan_in[edge["target"]] += 1
        fan_out[edge["source"]] += 1
    callers_of: Counter = Counter()
    for edge in call_edges:
        if edge["target"] and edge["confidence"] == CONFIRMED:
            callers_of[edge["target"]] += 1
    symbol_names = {symbol["id"]: symbol["qualname"] for symbol in symbols}
    summary = {
        "module_dependencies": len(module_edges),
        "external_dependencies": len(external_counter),
        "external_modules": dict(external_counter.most_common()),
        "call_relationships": len(call_edges),
        "confirmed_call_relationships": confidence_counts.get(CONFIRMED, 0),
        "approximate_call_relationships": confidence_counts.get(APPROXIMATE, 0),
        "external_call_relationships": confidence_counts.get(EXTERNAL, 0),
        "unresolved_call_relationships": confidence_counts.get(UNRESOLVED, 0),
        "contains_relationships": len(contains_edges),
        "circular_dependencies": len(cycles),
        "lazy_module_dependencies": sum(1 for edge in module_edges if edge["lazy"]),
        "hub_modules": [
            {"module": module, "fan_in": fan_in[module], "fan_out": fan_out[module]}
            for module in sorted(set(fan_in) | set(fan_out), key=lambda m: (-fan_in[m], -fan_out[m], m))[:5]
        ],
        "most_called_symbols": [
            {"id": target, "name": symbol_names.get(target, target), "confirmed_callers": count}
            for target, count in callers_of.most_common(5)
        ],
        "unresolved_references": len(unresolved),
    }
    return {
        "module_edges": module_edges,
        "call_edges": call_edges,
        "contains_edges": contains_edges,
        "cycles": cycles,
        "unresolved_references": unresolved[:MAX_UNRESOLVED_REPORTED],
        "summary": summary,
    }
