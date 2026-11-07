from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from .errors import NotFoundError
from .retrieval import LexicalIndex, VectorIndex, search_chunks
from .risks import SEVERITY_ORDER

CALLABLE_KINDS = frozenset({"function", "method", "nested_function"})
GRAPHABLE_KINDS = frozenset({"function", "method", "nested_function", "class", "module"})
MAX_SOURCE_LINES = 400
CONFIRMED = "confirmed"
APPROXIMATE = "approximate"


class RepositoryIndex:
    def __init__(self, analysis: dict[str, Any]) -> None:
        self.analysis = analysis
        self.analysis_id: str = analysis["analysis_id"]
        self.files: dict[str, dict[str, Any]] = {item["path"]: item for item in analysis["files"]}
        self.symbols: dict[str, dict[str, Any]] = {item["id"]: item for item in analysis["symbols"]}
        self.findings: dict[str, dict[str, Any]] = {item["id"]: item for item in analysis["findings"]}
        self.chunks: list[dict[str, Any]] = analysis["chunks"]
        self.cycles: list[dict[str, Any]] = analysis.get("cycles", [])
        self.edges: list[dict[str, Any]] = analysis["edges"]
        self.module_edges = [edge for edge in self.edges if edge["kind"] == "module_import"]
        self.call_edges = [edge for edge in self.edges if edge["kind"] == "calls"]
        self.contains_edges = [edge for edge in self.edges if edge["kind"] == "contains"]
        self.outgoing_calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.incoming_calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.candidate_callers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.call_edges:
            self.outgoing_calls[edge["source"]].append(edge)
            if edge["target"]:
                self.incoming_calls[edge["target"]].append(edge)
            for candidate in edge.get("candidates") or []:
                self.candidate_callers[candidate].append(edge)
        self.module_importers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.module_imports: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.module_edges:
            self.module_importers[edge["target"]].append(edge)
            self.module_imports[edge["source"]].append(edge)
        self.symbols_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for symbol in analysis["symbols"]:
            if symbol["kind"] != "module":
                self.symbols_by_file[symbol["file"]].append(symbol)
        for items in self.symbols_by_file.values():
            items.sort(key=lambda item: item["line"])
        self.module_to_file = {item["module"]: item["path"] for item in self.files.values()}
        self.cycle_modules = {module for cycle in self.cycles for module in cycle["modules"]}
        self._lexical: LexicalIndex | None = None

    @property
    def lexical(self) -> LexicalIndex:
        if self._lexical is None:
            self._lexical = LexicalIndex(self.chunks)
        return self._lexical

    def _symbol_name(self, identifier: str) -> str:
        symbol = self.symbols.get(identifier)
        if symbol is None:
            return identifier
        if symbol["kind"] == "module":
            return f"{symbol['file']} (top level)"
        return symbol["qualname"]

    def _file(self, path: str) -> dict[str, Any]:
        item = self.files.get(path)
        if item is None:
            raise NotFoundError("File not found in this analysis.")
        return item

    def _symbol(self, symbol_id: str) -> dict[str, Any]:
        item = self.symbols.get(symbol_id)
        if item is None or item["kind"] == "module":
            raise NotFoundError("Symbol not found in this analysis.")
        return item

    def summary(self) -> dict[str, Any]:
        analysis = self.analysis
        return {
            "analysis_id": self.analysis_id,
            "repository": analysis["repository"],
            "source_type": analysis["source_type"],
            "source_ref": analysis["source_ref"],
            "commit": analysis.get("commit"),
            "created_at": analysis["created_at"],
            "summary": analysis["summary"],
            "warnings": analysis["warnings"],
            "dependency_summary": analysis["dependency_summary"],
            "cycles": self.cycles,
            "findings_summary": Counter(item["severity"] for item in self.findings.values()),
            "most_complex": self.most_complex(),
            "largest_files": self.largest_files(),
        }

    def list_files(self) -> list[dict[str, Any]]:
        findings_per_file = Counter(item["file"] for item in self.findings.values())
        rows = []
        for path in sorted(self.files):
            file_record = self.files[path]
            symbols = self.symbols_by_file.get(path, [])
            rows.append({
                "path": path,
                "module": file_record["module"],
                "lines": file_record["lines"],
                "classes": sum(1 for item in symbols if item["kind"] == "class"),
                "functions": sum(1 for item in symbols if item["kind"] in CALLABLE_KINDS),
                "imports": len(file_record["imports"]),
                "findings": findings_per_file.get(path, 0),
                "parse_error": file_record["parse_error"],
            })
        return rows

    def file_detail(self, path: str) -> dict[str, Any]:
        file_record = self._file(path)
        symbols = self.symbols_by_file.get(path, [])
        classes = [item for item in symbols if item["kind"] == "class"]
        return {
            "path": path,
            "module": file_record["module"],
            "is_package": file_record["is_package"],
            "lines": file_record["lines"],
            "size_bytes": file_record["size_bytes"],
            "parse_error": file_record["parse_error"],
            "imports": file_record["imports"],
            "classes": [
                {"id": item["id"], "name": item["name"], "qualname": item["qualname"], "line": item["line"],
                 "end_line": item["end_line"], "bases": item["bases"],
                 "methods": [{"id": m["id"], "name": m["name"], "line": m["line"], "method_type": m["method_type"],
                              "is_async": m["is_async"], "complexity": m["complexity"]}
                             for m in symbols if m["kind"] == "method" and m["class_name"] == item["qualname"]]}
                for item in classes
            ],
            "symbols": [
                {"id": item["id"], "name": item["name"], "qualname": item["qualname"], "kind": item["kind"],
                 "line": item["line"], "end_line": item["end_line"], "is_async": item["is_async"],
                 "complexity": item["complexity"], "length": item["length"]}
                for item in symbols
            ],
            "findings": [item for item in self.findings.values() if item["file"] == path],
            "module_dependencies": {
                "imports": [{"module": edge["target"], "line": edge["line"], "lazy": edge["lazy"], "names": edge["names"]}
                            for edge in self.module_imports.get(file_record["module"], [])],
                "imported_by": [{"module": edge["source"], "line": edge["line"], "lazy": edge["lazy"]}
                                for edge in self.module_importers.get(file_record["module"], [])],
            },
        }

    def source_text(self, path: str) -> str:
        return self._file(path)["content"]

    def most_complex(self, limit: int = 5) -> list[dict[str, Any]]:
        callables = [item for item in self.symbols.values() if item["kind"] in CALLABLE_KINDS]
        ranked = sorted(callables, key=lambda item: (-item["complexity"], item["file"], item["line"]))[:limit]
        return [{"id": item["id"], "qualname": item["qualname"], "file": item["file"], "line": item["line"],
                 "complexity": item["complexity"], "length": item["length"]} for item in ranked]

    def largest_files(self, limit: int = 5) -> list[dict[str, Any]]:
        ranked = sorted(self.files.values(), key=lambda item: (-item["lines"], item["path"]))[:limit]
        return [{"path": item["path"], "lines": item["lines"],
                 "functions": sum(1 for s in self.symbols_by_file.get(item["path"], []) if s["kind"] in CALLABLE_KINDS)}
                for item in ranked]

    def text_search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        results: list[dict[str, Any]] = []
        if not needle:
            return results
        for path in sorted(self.files):
            for number, line in enumerate(self.files[path]["content"].splitlines(), start=1):
                if needle not in line.lower():
                    continue
                enclosing = self._enclosing_symbol(path, number)
                results.append({"file": path, "line": number, "text": line.strip()[:200],
                                "symbol": enclosing["qualname"] if enclosing else None,
                                "symbol_id": enclosing["id"] if enclosing else None})
                if len(results) >= limit:
                    return results
        return results

    def import_search(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        results: list[dict[str, Any]] = []
        if not needle:
            return results
        for path in sorted(self.files):
            for record in self.files[path]["imports"]:
                haystack = f"{record.get('module') or ''} {record.get('symbol') or ''}".lower()
                if needle not in haystack:
                    continue
                if record["kind"] == "from":
                    statement = f"from {'.' * record['level']}{record['module']} import {record['symbol']}"
                else:
                    statement = f"import {record['module']}"
                results.append({"file": path, "line": record["line"], "statement": statement,
                                "module": record["module"], "symbol": record.get("symbol")})
                if len(results) >= limit:
                    return results
        return results

    def _enclosing_symbol(self, path: str, line: int) -> dict[str, Any] | None:
        candidates = [item for item in self.symbols_by_file.get(path, []) if item["start_line"] <= line <= item["end_line"]]
        return min(candidates, key=lambda item: item["length"]) if candidates else None

    def list_symbols(self, query: str | None = None, file: str | None = None, kind: str | None = None,
                     limit: int = 200) -> list[dict[str, Any]]:
        needle = (query or "").strip().lower()
        results = []
        for symbol in self.symbols.values():
            if symbol["kind"] == "module":
                continue
            if file and symbol["file"] != file:
                continue
            if kind and symbol["kind"] != kind:
                continue
            if needle and needle not in symbol["qualname"].lower() and needle not in symbol["file"].lower():
                continue
            results.append({
                "id": symbol["id"], "name": symbol["name"], "qualname": symbol["qualname"], "kind": symbol["kind"],
                "file": symbol["file"], "line": symbol["line"], "class_name": symbol["class_name"],
                "complexity": symbol["complexity"], "is_async": symbol["is_async"],
            })
        results.sort(key=lambda item: (item["file"], item["line"]))
        return results[: max(1, min(limit, 1000))]

    def resolve_symbols(self, name: str, file: str | None = None) -> list[dict[str, Any]]:
        needle = name.strip()
        exact = [s for s in self.symbols.values() if s["kind"] != "module" and (s["id"] == needle or s["qualname"] == needle)]
        if not exact:
            exact = [s for s in self.symbols.values() if s["kind"] != "module" and s["name"] == needle]
        if file:
            exact = [s for s in exact if s["file"] == file]
        return exact

    def symbol_detail(self, symbol_id: str) -> dict[str, Any]:
        symbol = self._symbol(symbol_id)
        lines = self.files[symbol["file"]]["content"].splitlines()
        start, end = symbol["start_line"], symbol["end_line"]
        body = lines[start - 1:end]
        truncated = len(body) > MAX_SOURCE_LINES
        callers = self._callers(symbol_id)
        callees = [self._callee_view(edge) for edge in self.outgoing_calls.get(symbol_id, [])]
        members = [s["id"] for s in self.symbols_by_file.get(symbol["file"], [])
                   if s["kind"] == "method" and s["class_name"] == symbol["qualname"]] if symbol["kind"] == "class" else []
        return {
            **{key: symbol[key] for key in ("id", "name", "qualname", "kind", "file", "module", "class_name", "is_async",
                                            "is_nested", "method_type", "line", "end_line", "length", "complexity",
                                            "decorators", "arguments", "returns", "docstring", "bases")},
            "source": {"start_line": start, "end_line": end, "text": "\n".join(body[:MAX_SOURCE_LINES]), "truncated": truncated},
            "members": members,
            "callers": callers,
            "callees": callees,
            "findings": [item for item in self.findings.values() if item["symbol_id"] == symbol_id],
        }

    def _callee_view(self, edge: dict[str, Any]) -> dict[str, Any]:
        target = edge["target"]
        return {
            "target": target,
            "target_name": self._symbol_name(target) if target else edge["target_name"],
            "line": edge["line"],
            "resolution": edge["resolution"],
            "confidence": edge["confidence"],
            "candidates": [{"id": c, "name": self._symbol_name(c)} for c in edge.get("candidates") or []],
        }

    def _callers(self, symbol_id: str) -> list[dict[str, Any]]:
        views = []
        for edge in self.incoming_calls.get(symbol_id, []):
            source = self.symbols.get(edge["source"], {})
            views.append({"source": edge["source"], "source_name": self._symbol_name(edge["source"]),
                          "file": source.get("file"), "line": edge["line"], "resolution": edge["resolution"],
                          "confidence": edge["confidence"]})
        for edge in self.candidate_callers.get(symbol_id, []):
            source = self.symbols.get(edge["source"], {})
            views.append({"source": edge["source"], "source_name": self._symbol_name(edge["source"]),
                          "file": source.get("file"), "line": edge["line"], "resolution": edge["resolution"],
                          "confidence": APPROXIMATE})
        return views

    def search(self, query: str, limit: int = 8, vector_index: VectorIndex | None = None,
               query_vector: np.ndarray | None = None) -> list[dict[str, Any]]:
        return search_chunks(self.chunks, self.lexical, query, limit=limit,
                             vector_index=vector_index, query_vector=query_vector)

    def graph_facts(self, question: str) -> list[str]:
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question))
        facts: list[str] = []
        for symbol in self.symbols.values():
            if symbol["kind"] == "module" or len(facts) >= 6:
                continue
            if symbol["name"] in tokens and symbol["name"] not in {"main", "run", "get", "set"} or symbol["qualname"] in tokens:
                callers = self._callers(symbol["id"])
                callees = [self._callee_view(edge) for edge in self.outgoing_calls.get(symbol["id"], [])]
                caller_text = ", ".join(
                    f"{c['source_name']} ({c['file']} line {c['line']}, {c['confidence']})" for c in callers[:6]
                ) or "none found"
                callee_text = ", ".join(
                    f"{c['target_name']} (line {c['line']}, {c['confidence']})" for c in callees[:8]
                ) or "none found"
                facts.append(
                    f"{symbol['qualname']} is defined in {symbol['file']} line {symbol['line']}. "
                    f"Static callers: {caller_text}. Static calls made: {callee_text}."
                )
        for module, file_path in self.module_to_file.items():
            short_name = module.split(".")[-1]
            if short_name in tokens and len(facts) < 8:
                importers = sorted({edge["source"] for edge in self.module_importers.get(module, [])})
                imports = sorted({edge["target"] for edge in self.module_imports.get(module, [])})
                facts.append(
                    f"Module {module} ({file_path}) is imported by: {', '.join(importers) or 'no internal module'}. "
                    f"It imports internal modules: {', '.join(imports) or 'none'}."
                )
        return facts

    def dependency_graph(self, scope: str = "modules", confidence: str = "confirmed", max_nodes: int = 150,
                         focus: str | None = None, query: str | None = None, module: str | None = None) -> dict[str, Any]:
        max_nodes = max(10, min(max_nodes, 500))
        if scope == "modules":
            nodes, edges = self._module_graph()
        else:
            nodes, edges = self._function_graph(confidence)
        if module and scope == "functions":
            nodes, edges = self._module_scope(module, edges)
        neighbourhood_ids = None
        if focus:
            neighbourhood_ids = {focus} | {e["source"] for e in edges if e["target"] == focus} | {
                e["target"] for e in edges if e["source"] == focus}
        if query:
            needle = query.strip().lower()
            matched = {n["id"] for n in nodes if needle in n["label"].lower() or needle in n.get("file", "").lower()}
            neighbours = {e["source"] for e in edges if e["target"] in matched} | {e["target"] for e in edges if e["source"] in matched}
            neighbourhood_ids = (neighbourhood_ids or set(n["id"] for n in nodes)) & (matched | neighbours)
        if neighbourhood_ids is not None:
            nodes = [n for n in nodes if n["id"] in neighbourhood_ids]
            edges = [e for e in edges if e["source"] in neighbourhood_ids and e["target"] in neighbourhood_ids]
        if scope == "modules" and not focus and not query:
            connected = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
            nodes = [node for node in nodes if node["id"] in connected]
        degree = Counter()
        for edge in edges:
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
        total_nodes = len(nodes)
        if len(nodes) > max_nodes:
            keep = {n["id"] for n in sorted(nodes, key=lambda n: (-degree[n["id"]], n["label"]))[:max_nodes]}
            nodes = [n for n in nodes if n["id"] in keep]
            edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
        for node in nodes:
            node["degree"] = degree[node["id"]]
        return {
            "scope": scope,
            "confidence": confidence,
            "nodes": nodes,
            "edges": edges,
            "total_nodes": total_nodes,
            "total_edges": len(edges),
            "truncated": total_nodes > len(nodes),
        }

    def _module_graph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cycle_membership = self.cycle_modules
        nodes = []
        for file_record in self.files.values():
            module = file_record["module"]
            symbols = self.symbols_by_file.get(file_record["path"], [])
            nodes.append({
                "id": module, "label": module, "file": file_record["path"], "kind": "module",
                "functions": sum(1 for s in symbols if s["kind"] in CALLABLE_KINDS),
                "classes": sum(1 for s in symbols if s["kind"] == "class"),
                "fan_in": len(self.module_importers.get(module, [])),
                "fan_out": len(self.module_imports.get(module, [])),
                "in_cycle": module in cycle_membership,
            })
        node_ids = {node["id"] for node in nodes}
        edges = []
        for index, edge in enumerate(self.module_edges):
            if edge["source"] in node_ids and edge["target"] in node_ids:
                edges.append({
                    "id": f"m{index}", "source": edge["source"], "target": edge["target"],
                    "confidence": CONFIRMED, "lazy": edge["lazy"], "names": edge["names"], "line": edge["line"],
                    "label": ", ".join(edge["names"][:3]) if edge["names"] else "import",
                    "in_cycle": edge["source"] in cycle_membership and edge["target"] in cycle_membership,
                })
        return nodes, edges

    def _function_graph(self, confidence: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allowed = {CONFIRMED} if confidence != "all" else {CONFIRMED, APPROXIMATE}
        edges = []
        for index, edge in enumerate(self.call_edges):
            if edge["target"] is None or edge["confidence"] not in allowed:
                continue
            if edge["source"] == edge["target"]:
                continue
            edges.append({
                "id": f"c{index}", "source": edge["source"], "target": edge["target"],
                "confidence": edge["confidence"], "resolution": edge["resolution"], "line": edge["line"],
                "label": f"{edge['resolution']} · line {edge['line']}", "lazy": False,
            })
        node_ids = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
        return [self._function_node(node_id) for node_id in sorted(node_ids) if node_id in self.symbols], edges

    def _function_node(self, node_id: str) -> dict[str, Any]:
        symbol = self.symbols[node_id]
        return {
            "id": node_id, "label": self._symbol_name(node_id), "file": symbol["file"],
            "kind": symbol["kind"], "module": symbol["module"], "complexity": symbol["complexity"],
            "line": symbol["line"],
        }

    def _module_scope(self, module: str, edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        path = self.module_to_file.get(module)
        if path is None:
            raise NotFoundError("Module not found in this analysis.")
        anchors = {item["id"] for item in self.symbols_by_file.get(path, [])}
        kept_edges = [edge for edge in edges if edge["source"] in anchors or edge["target"] in anchors]
        node_ids = anchors | {edge["source"] for edge in kept_edges} | {edge["target"] for edge in kept_edges}
        return [self._function_node(node_id) for node_id in sorted(node_ids)], kept_edges

    def risks(self, min_severity: str = "info", category: str | None = None, rule_id: str | None = None,
              file: str | None = None) -> list[dict[str, Any]]:
        threshold = SEVERITY_ORDER.get(min_severity, SEVERITY_ORDER["info"])
        results = []
        for finding in self.findings.values():
            if SEVERITY_ORDER[finding["severity"]] > threshold:
                continue
            if category and finding["category"] != category:
                continue
            if rule_id and finding["rule_id"] != rule_id:
                continue
            if file and finding["file"] != file:
                continue
            results.append(finding)
        return sorted(results, key=lambda item: (SEVERITY_ORDER[item["severity"]], item["file"], item["line"]))

    def finding(self, finding_id: str) -> dict[str, Any]:
        item = self.findings.get(finding_id)
        if item is None:
            raise NotFoundError("Finding not found in this analysis.")
        return item

    def call_flow(self, symbol_id: str, depth: int = 2, max_nodes: int = 60) -> dict[str, Any]:
        root_symbol = self._symbol(symbol_id)
        lines: list[str] = []
        counter = {"nodes": 0}

        def expand(node_id: str, level: int, ancestry: frozenset[str]) -> list[dict[str, Any]]:
            children = []
            if level >= depth:
                return children
            for edge in self.outgoing_calls.get(node_id, []):
                if counter["nodes"] >= max_nodes:
                    break
                if edge["target"] is None or edge["confidence"] == "unresolved":
                    continue
                if edge["confidence"] == APPROXIMATE and edge["resolution"] != "name_match":
                    continue
                target = edge["target"]
                counter["nodes"] += 1
                child = {
                    "id": target, "name": self._symbol_name(target), "line": edge["line"],
                    "confidence": edge["confidence"], "resolution": edge["resolution"],
                    "recursive": target in ancestry, "children": [],
                }
                indent = "  " * (level + 1)
                lines.append(f"{indent}{self._symbol_name(node_id)} -> {child['name']} "
                             f"(line {edge['line']}, {edge['confidence']}"
                             f"{', recursive' if child['recursive'] else ''})")
                if not child["recursive"]:
                    child["children"] = expand(target, level + 1, ancestry | {target})
                children.append(child)
            return children

        tree = {
            "id": root_symbol["id"], "name": root_symbol["qualname"], "line": root_symbol["line"],
            "confidence": None, "resolution": None, "recursive": False,
            "children": expand(symbol_id, 0, frozenset({symbol_id})),
        }
        return {"root": symbol_id, "depth": depth, "tree": tree, "lines": lines, "truncated": counter["nodes"] >= max_nodes}

    def dependency_summary_for_module(self, module: str) -> dict[str, Any]:
        return {
            "module": module,
            "file": self.module_to_file.get(module),
            "imports": [{"module": e["target"], "line": e["line"], "lazy": e["lazy"], "names": e["names"]}
                        for e in self.module_imports.get(module, [])],
            "imported_by": [{"module": e["source"], "line": e["line"], "lazy": e["lazy"]}
                            for e in self.module_importers.get(module, [])],
            "in_cycle": module in self.cycle_modules,
        }
