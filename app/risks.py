from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
SUBPROCESS_FUNCTIONS = frozenset({"run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"})
WRITE_MODE_CHARS = frozenset("wax+")
SECRET_NAME_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|private[_-]?key|auth[_-]?token|"
    r"access[_-]?token|client[_-]?secret|token)$"
)
NON_SECRET_SUFFIX_PATTERN = re.compile(r"(?i)(_name|_url|_uri|_path|_type|_label|_field|_header|_env|_var|_file)$")
SECRET_VALUE_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)
SQL_PATTERN = re.compile(r"(?is)\b(select\b.+\bfrom\b|insert\s+into\b|update\s+\w+\s+set\b|delete\s+from\b)")
STRING_LITERAL_PATTERN = re.compile(r"""(['"])(?:(?!\1).){8,}\1""")

RULES: dict[str, dict[str, str]] = {
    "RM-ERR-001": {
        "title": "Bare except clause", "category": "error-handling", "severity": "medium",
        "legacy_rule": "bare-except",
        "explanation": "A bare 'except:' catches every exception, including KeyboardInterrupt and SystemExit, which can hide real failures.",
        "remediation": "Catch the specific exception types the block can handle, and log or re-raise anything unexpected.",
    },
    "RM-ERR-002": {
        "title": "Exception handler discards the error", "category": "error-handling", "severity": "low",
        "explanation": "The handler body only passes, continues or uses an ellipsis, so the error leaves no trace.",
        "remediation": "Log the exception with context, handle it explicitly, or re-raise it. If ignoring is intended, narrow the exception type and document why.",
    },
    "RM-SEC-001": {
        "title": "Possible hardcoded credential", "category": "secrets", "severity": "high",
        "explanation": "A value that resembles a credential is written directly in source. The value is redacted in this report. This is a heuristic match, and the value may be a placeholder.",
        "remediation": "Load the secret from an environment variable or secret manager, rotate it if it was ever committed, and enable secret scanning on the repository.",
    },
    "RM-SEC-002": {
        "title": "Subprocess call may run through the shell", "category": "command-execution", "severity": "high",
        "explanation": "shell=True or os.system passes the command through a shell. If any part of the command comes from untrusted input, command injection may be possible.",
        "remediation": "Pass the command as a list of arguments without shell=True, and validate every dynamic argument.",
    },
    "RM-SEC-003": {
        "title": "Dynamic code execution", "category": "code-execution", "severity": "high",
        "explanation": "eval() and exec() execute Python code from a string. If that string is influenced by external input, arbitrary code may run.",
        "remediation": "Replace with explicit parsing (for example ast.literal_eval for literals) or a dispatch table.",
    },
    "RM-SEC-004": {
        "title": "Unsafe deserialization", "category": "deserialization", "severity": "medium",
        "explanation": "pickle, marshal and yaml.load without a safe loader can construct arbitrary objects from data. Untrusted input can lead to code execution.",
        "remediation": "Use json or yaml.safe_load for untrusted data, or verify the data source before deserializing.",
    },
    "RM-SEC-005": {
        "title": "TLS certificate verification disabled", "category": "transport-security", "severity": "high",
        "explanation": "verify=False turns off certificate checks, which allows interception of the connection.",
        "remediation": "Keep verification enabled and supply a trusted CA bundle when an internal certificate authority is used.",
    },
    "RM-SQL-001": {
        "title": "SQL statement built with string formatting", "category": "injection", "severity": "medium",
        "explanation": "The SQL text appears to be assembled with f-strings, concatenation, % formatting or str.format(). If user-controlled values are inserted this way, SQL injection may be possible.",
        "remediation": "Use parameterized queries with placeholders and pass values as separate arguments.",
    },
    "RM-FILE-001": {
        "title": "Archive extraction without member validation", "category": "file-handling", "severity": "medium",
        "explanation": "extractall() without validation can write files outside the destination when the archive contains crafted member paths.",
        "remediation": "Validate member paths before extraction, or use the tarfile extraction filter such as filter='data'.",
    },
    "RM-FILE-002": {
        "title": "World-writable file permissions", "category": "file-handling", "severity": "medium",
        "explanation": "chmod with mode 0o777 or 0o666 makes the file writable by every user on the system.",
        "remediation": "Use the least permissive mode that works, such as 0o600 or 0o644.",
    },
    "RM-FILE-003": {
        "title": "File written to a computed path", "category": "file-handling", "severity": "low",
        "explanation": "open() is used in a write mode with a path that is not a literal. If external input influences the path, files may land in unintended locations.",
        "remediation": "Resolve the path, confirm it stays inside the expected directory, and reject unexpected names.",
    },
    "RM-QUAL-001": {
        "title": "High cyclomatic complexity", "category": "maintainability", "severity": "medium",
        "explanation": "The function contains many decision points, which makes its behaviour harder to test and review.",
        "remediation": "Split the function into smaller units with clear responsibilities and add tests for each branch.",
    },
    "RM-QUAL-002": {
        "title": "Long function", "category": "maintainability", "severity": "low",
        "explanation": "The function body is very long, which tends to mix responsibilities and increases review effort.",
        "remediation": "Extract cohesive helper functions and keep each function focused on one task.",
    },
    "RM-QUAL-003": {
        "title": "assert used in application code", "category": "maintainability", "severity": "info",
        "explanation": "assert statements are removed when Python runs with optimisation enabled, so they must not be the only validation.",
        "remediation": "Raise an explicit exception for validation that must always run.",
    },
    "RM-DUP-001": {
        "title": "Duplicate function body", "category": "duplication", "severity": "low",
        "explanation": "The same statements appear in more than one function.",
        "remediation": "Move the shared logic into one function and call it from each place.",
    },
    "RM-DEAD-001": {
        "title": "Function may be unused", "category": "maintenance", "severity": "info",
        "explanation": "No other code in the project uses this name. It may be dead code, or it may be called from outside the project.",
        "remediation": "Confirm it is not called from outside the project, then remove it or add a test that uses it.",
    },
    "STY-001": {
        "title": "print() call", "category": "style", "severity": "info", "legacy_rule": "print-call",
        "explanation": "print() writes directly to standard output and is not controlled by logging configuration.",
        "remediation": "Use the logging module in application code.",
    },
    "STY-002": {
        "title": "None compared with == or !=", "category": "style", "severity": "info", "legacy_rule": "none-comparison",
        "explanation": "Equality comparison with None works, but identity checks are the idiomatic form.",
        "remediation": "Use 'is None' or 'is not None'.",
    },
}


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _constant_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _constant_str(node.slice)
    return None


def _looks_like_secret_value(value: str) -> bool:
    if len(value) < 8 or any(character.isspace() for character in value):
        return False
    if value.startswith(("<", "{", "$", "%")) or "{" in value:
        return False
    return len(set(value)) > 3


def _redact(text: str) -> str:
    return STRING_LITERAL_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>{match.group(1)}", text)


def _is_string_built(node: ast.expr) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"


def _sql_text(node: ast.expr) -> str:
    if isinstance(node, ast.JoinedStr):
        return " ".join(part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str))
    if isinstance(node, ast.BinOp):
        return f"{_sql_text(node.left)} {_sql_text(node.right)}"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _constant_str(node.func.value) or ""
    return _constant_str(node) or ""


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _is_silent_body(body: list[ast.stmt]) -> bool:
    for statement in body:
        if isinstance(statement, (ast.Pass, ast.Continue)):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and statement.value.value is Ellipsis:
            continue
        return False
    return True


class _RiskCollector:
    def __init__(self, relative_path: str, lines: list[str]) -> None:
        self.relative_path = relative_path
        self.lines = lines
        self.findings: list[dict[str, Any]] = []
        self.seen: set[tuple[str, int]] = set()

    def line_text(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()[:220]
        return ""

    def add(self, rule_id: str, line: int, end_line: int | None = None, severity: str | None = None,
            evidence: str | None = None, detail: str | None = None) -> None:
        key = (rule_id, line)
        if key in self.seen:
            return
        self.seen.add(key)
        meta = RULES[rule_id]
        text = evidence if evidence is not None else self.line_text(line)
        digest = hashlib.sha1(f"{self.relative_path}:{line}:{rule_id}:{text}".encode("utf-8")).hexdigest()[:8]
        explanation = meta["explanation"] + (f" {detail}" if detail else "")
        self.findings.append({
            "id": f"{rule_id}-{digest}",
            "rule_id": rule_id,
            "legacy_rule": meta.get("legacy_rule"),
            "title": meta["title"],
            "category": meta["category"],
            "severity": severity or meta["severity"],
            "confidence": "heuristic",
            "file": self.relative_path,
            "line": line,
            "end_line": end_line or line,
            "evidence": text,
            "explanation": explanation,
            "remediation": meta["remediation"],
            "why_it_matters": WHY_IT_MATTERS.get(rule_id, ""),
            "symbol_id": None,
        })

    def check_secret_assignment(self, target: ast.AST | None, value: ast.AST | None, line: int) -> None:
        name = _target_name(target) if target is not None else None
        text = _constant_str(value)
        if not name or text is None:
            return
        if SECRET_NAME_PATTERN.search(name) and not NON_SECRET_SUFFIX_PATTERN.search(name) and _looks_like_secret_value(text):
            self.add("RM-SEC-001", line, evidence=_redact(self.line_text(line)))

    def check_call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        final = name.rsplit(".", 1)[-1] if name else ""
        line = node.lineno
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        for keyword in node.keywords:
            if keyword.arg and SECRET_NAME_PATTERN.search(keyword.arg) and _constant_str(keyword.value):
                if _looks_like_secret_value(_constant_str(keyword.value) or ""):
                    self.add("RM-SEC-001", line, evidence=_redact(self.line_text(line)))
        if name in {"eval", "exec"}:
            dynamic = not (node.args and isinstance(node.args[0], ast.Constant))
            self.add("RM-SEC-003", line, severity="high" if dynamic else "medium")
        elif name == "os.system":
            self.add("RM-SEC-002", line, severity="high")
        elif name == "os.popen":
            self.add("RM-SEC-002", line, severity="medium")
        elif name.startswith("subprocess.") and final in SUBPROCESS_FUNCTIONS and _is_true(keywords.get("shell")):
            self.add("RM-SEC-002", line, severity="high")
        elif name in {"pickle.load", "pickle.loads", "marshal.load", "marshal.loads", "dill.loads"}:
            self.add("RM-SEC-004", line, severity="medium")
        elif name in {"yaml.load", "yaml.unsafe_load"}:
            loader = _call_name(keywords["Loader"]) if "Loader" in keywords else ""
            if name == "yaml.unsafe_load" or not loader or "Safe" not in loader:
                self.add("RM-SEC-004", line, severity="high")
        if _is_false(keywords.get("verify")):
            self.add("RM-SEC-005", line, severity="high")
        if final in {"execute", "executemany", "executescript"} and node.args and _is_string_built(node.args[0]):
            if SQL_PATTERN.search(_sql_text(node.args[0])):
                self.add("RM-SQL-001", line)
        if final == "extractall" and "filter" not in keywords:
            self.add("RM-FILE-001", line)
        if name == "os.chmod" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            if node.args[1].value in {0o777, 0o666}:
                self.add("RM-FILE-002", line)
        if name == "open" and node.args and not isinstance(node.args[0], ast.Constant):
            mode_node = node.args[1] if len(node.args) > 1 else keywords.get("mode")
            mode = _constant_str(mode_node) or ""
            if WRITE_MODE_CHARS & set(mode):
                self.add("RM-FILE-003", line)
        if name == "print":
            self.add("STY-001", line)

    def check_compare(self, node: ast.Compare) -> None:
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            operands = [node.left, *node.comparators]
            if any(isinstance(item, ast.Constant) and item.value is None for item in operands):
                self.add("STY-002", node.lineno)

    def check_constant_patterns(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(node.value):
                self.add("RM-SEC-001", node.lineno, evidence=_redact(self.line_text(node.lineno)))
                return

    def visit_tree(self, tree: ast.Module, is_test_file: bool) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    self.add("RM-ERR-001", node.lineno, evidence="except:")
                if _is_silent_body(node.body):
                    broad = node.type is None or _call_name(node.type) in {"Exception", "BaseException"}
                    self.add("RM-ERR-002", node.lineno, severity="low" if broad else "info")
            elif isinstance(node, ast.Call):
                self.check_call(node)
            elif isinstance(node, ast.Compare):
                self.check_compare(node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    self.check_secret_assignment(target, node.value, node.lineno)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self.check_secret_assignment(node.target, node.value, node.lineno)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    key_text = _constant_str(key)
                    if key_text and SECRET_NAME_PATTERN.search(key_text) and _looks_like_secret_value(_constant_str(value) or ""):
                        self.add("RM-SEC-001", node.lineno, evidence=_redact(self.line_text(node.lineno)))
            elif isinstance(node, ast.Assert) and not is_test_file:
                self.add("RM-QUAL-003", node.lineno)
            elif isinstance(node, ast.Constant):
                self.check_constant_patterns(node)


def _complexity_findings(collector: _RiskCollector, symbols: list[dict[str, Any]]) -> None:
    for symbol in symbols:
        if symbol["kind"] not in {"function", "method", "nested_function"}:
            continue
        if symbol["complexity"] >= 15:
            severity = "high" if symbol["complexity"] >= 25 else "medium"
            collector.add("RM-QUAL-001", symbol["line"], symbol["end_line"], severity=severity,
                          evidence=f"{symbol['qualname']} has complexity {symbol['complexity']}",
                          detail=f"Measured complexity for {symbol['qualname']} is {symbol['complexity']}.")
        if symbol["length"] >= 100:
            collector.add("RM-QUAL-002", symbol["line"], symbol["end_line"],
                          evidence=f"{symbol['qualname']} spans {symbol['length']} lines",
                          detail=f"{symbol['qualname']} spans {symbol['length']} lines.")


def analyze_risks(tree: ast.Module, relative_path: str, source_lines: list[str],
                  symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collector = _RiskCollector(relative_path, source_lines)
    is_test_file = "test" in relative_path.lower().split("/")[-1] or "/tests/" in f"/{relative_path.lower()}/"
    collector.visit_tree(tree, is_test_file)
    _complexity_findings(collector, [item for item in symbols if item["file"] == relative_path])
    if is_test_file:
        for finding in collector.findings:
            if finding["rule_id"] == "RM-SEC-001":
                finding["severity"] = "low"
    return sorted(collector.findings, key=lambda item: (SEVERITY_ORDER[item["severity"]], item["line"]))


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = {level: 0 for level in SEVERITY_ORDER}
    by_category: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for finding in findings:
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
        by_category[finding["category"]] = by_category.get(finding["category"], 0) + 1
        by_rule[finding["rule_id"]] = by_rule.get(finding["rule_id"], 0) + 1
    return {"total": len(findings), "by_severity": by_severity, "by_category": by_category, "by_rule": by_rule}


WHY_IT_MATTERS: dict[str, str] = {
    "RM-ERR-001": "A bare except hides real errors, including ones you need to see.",
    "RM-ERR-002": "Silently discarded errors make bugs much harder to find later.",
    "RM-SEC-001": "Anyone who can read the repository can use a committed secret.",
    "RM-SEC-002": "A shell command built from untrusted input can run unintended commands.",
    "RM-SEC-003": "Evaluating strings as code can run any instruction they contain.",
    "RM-SEC-004": "Loading untrusted serialized data can execute code.",
    "RM-SEC-005": "Without certificate checks, traffic can be read or changed in transit.",
    "RM-SQL-001": "String-built SQL is a common route for injection attacks.",
    "RM-FILE-001": "Archives with crafted paths can overwrite files outside the target folder.",
    "RM-FILE-002": "World-writable files can be changed by any user on the machine.",
    "RM-FILE-003": "A computed path can point somewhere you did not intend.",
    "RM-QUAL-001": "Functions with many branches are hard to test completely and easy to break.",
    "RM-QUAL-002": "Very long functions are harder to read, review and reuse.",
    "RM-QUAL-003": "Optimised runs remove asserts, so checks can silently disappear.",
    "RM-DUP-001": "Two copies of the same logic can drift apart when only one is fixed.",
    "RM-DEAD-001": "Unused code adds reading cost and can hide outdated logic.",
    "STY-001": "Printed output bypasses the logging settings used in production.",
    "STY-002": "Identity checks are the expected form for None.",
}

MIN_DUPLICATE_STATEMENTS = 4
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def make_finding(rule_id: str, file: str, line: int, end_line: int | None, evidence: str,
                 detail: str | None = None) -> dict[str, Any]:
    meta = RULES[rule_id]
    digest = hashlib.sha1(f"{file}:{line}:{rule_id}:{evidence}".encode("utf-8")).hexdigest()[:8]
    return {
        "id": f"{rule_id}-{digest}",
        "rule_id": rule_id,
        "legacy_rule": meta.get("legacy_rule"),
        "title": meta["title"],
        "category": meta["category"],
        "severity": meta["severity"],
        "confidence": "heuristic",
        "file": file,
        "line": line,
        "end_line": end_line or line,
        "evidence": evidence,
        "explanation": meta["explanation"] + (f" {detail}" if detail else ""),
        "why_it_matters": WHY_IT_MATTERS.get(rule_id, ""),
        "remediation": meta["remediation"],
        "symbol_id": None,
    }


def body_fingerprints(tree: ast.Module, relative_path: str) -> list[dict[str, Any]]:
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        if len(body) < MIN_DUPLICATE_STATEMENTS:
            continue
        digest = hashlib.sha1(ast.dump(ast.Module(body=body, type_ignores=[])).encode("utf-8")).hexdigest()
        results.append({"hash": digest, "file": relative_path, "line": node.lineno,
                        "end_line": node.end_lineno or node.lineno, "name": node.name})
    return results


def duplicate_findings(fingerprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in fingerprints:
        groups.setdefault(item["hash"], []).append(item)
    findings = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: (item["file"], item["line"]))
        first = members[0]
        others = ", ".join(f"{item['file']} line {item['line']}" for item in members[1:4])
        findings.append(make_finding(
            "RM-DUP-001", first["file"], first["line"], first["end_line"],
            evidence=f"{first['name']} has the same statements as {len(members) - 1} other function(s)",
            detail=f"The same statements also appear in {others}.",
        ))
    return findings


def unused_function_findings(symbols: list[dict[str, Any]], identifier_counts: Counter) -> list[dict[str, Any]]:
    findings = []
    for symbol in symbols:
        if symbol["kind"] not in {"function", "method"}:
            continue
        name = symbol["name"]
        if name.startswith("__") or name.startswith("test") or name == "main" or symbol["decorators"]:
            continue
        if identifier_counts.get(name, 0) > 1:
            continue
        findings.append(make_finding(
            "RM-DEAD-001", symbol["file"], symbol["line"], symbol["end_line"],
            evidence=f"{symbol['qualname']} is never referenced by name",
        ))
    return findings
