from __future__ import annotations

import ast

from app.risks import analyze_risks, summarize_findings


def _findings(source: str, path: str = "app/module.py"):
    tree = ast.parse(source)
    return analyze_risks(tree, path, source.splitlines(), symbols=[])


def _rules(source: str, path: str = "app/module.py"):
    return {item["rule_id"] for item in _findings(source, path)}


def test_bare_except_and_silent_handler_are_reported():
    source = "def run():\n    try:\n        work()\n    except:\n        pass\n"
    findings = _findings(source)
    rules = {item["rule_id"] for item in findings}
    assert {"RM-ERR-001", "RM-ERR-002"} <= rules
    bare = next(item for item in findings if item["rule_id"] == "RM-ERR-001")
    assert bare["legacy_rule"] == "bare-except"
    assert bare["line"] == 4
    assert bare["confidence"] == "heuristic"


def test_handled_exception_is_not_flagged_as_silent():
    source = "def run():\n    try:\n        work()\n    except ValueError as exc:\n        log(exc)\n"
    assert "RM-ERR-002" not in _rules(source)
    assert "RM-ERR-001" not in _rules(source)


def test_shell_true_subprocess_is_high_severity():
    source = "import subprocess\nsubprocess.run(cmd, shell=True)\nsubprocess.run(['ls'])\n"
    findings = [item for item in _findings(source) if item["rule_id"] == "RM-SEC-002"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert findings[0]["line"] == 2


def test_os_system_is_reported():
    assert "RM-SEC-002" in _rules("import os\nos.system('ls')\n")


def test_eval_with_dynamic_argument_is_high_and_literal_is_medium():
    dynamic = _findings("def f(x):\n    return eval(x)\n")
    literal = _findings("result = eval('1 + 1')\n")
    assert next(i for i in dynamic if i["rule_id"] == "RM-SEC-003")["severity"] == "high"
    assert next(i for i in literal if i["rule_id"] == "RM-SEC-003")["severity"] == "medium"


def test_unsafe_yaml_and_pickle_deserialization():
    assert "RM-SEC-004" in _rules("import yaml\ndata = yaml.load(text)\n")
    assert "RM-SEC-004" not in _rules("import yaml\ndata = yaml.load(text, Loader=yaml.SafeLoader)\n")
    assert "RM-SEC-004" in _rules("import pickle\nobj = pickle.loads(blob)\n")


def test_tls_verification_disabled_is_high():
    finding = next(i for i in _findings("import httpx\nhttpx.get(url, verify=False)\n") if i["rule_id"] == "RM-SEC-005")
    assert finding["severity"] == "high"


def test_sql_built_with_fstring_is_flagged_but_parameterized_is_not():
    risky = _findings("def f(c, uid):\n    c.execute(f\"SELECT * FROM users WHERE id = '{uid}'\")\n")
    assert any(item["rule_id"] == "RM-SQL-001" for item in risky)
    safe = _findings("def f(c, uid):\n    c.execute('SELECT * FROM users WHERE id = ?', (uid,))\n")
    assert not any(item["rule_id"] == "RM-SQL-001" for item in safe)
    concatenated = _findings("def f(c, uid):\n    c.execute('SELECT name FROM t WHERE id = ' + uid)\n")
    assert any(item["rule_id"] == "RM-SQL-001" for item in concatenated)


def test_hardcoded_credentials_are_redacted_in_evidence():
    secret = "super-secret-value-123"
    findings = _findings(f"API_TOKEN = \"{secret}\"\n")
    finding = next(item for item in findings if item["rule_id"] == "RM-SEC-001")
    assert secret not in finding["evidence"]
    assert "<redacted>" in finding["evidence"]
    assert all(secret not in str(value) for item in findings for value in item.values())
    assert finding["severity"] == "high"


def test_placeholder_and_environment_values_are_not_flagged():
    assert "RM-SEC-001" not in _rules("PASSWORD = os.getenv('PASSWORD')\n")
    assert "RM-SEC-001" not in _rules("password = ''\n")
    assert "RM-SEC-001" not in _rules("auth_header_name = 'Authorization-Header'\n")


def test_known_token_formats_are_detected_anywhere():
    token = "ghp_" + "a" * 36
    findings = _findings(f"client = make(\"{token}\")\n")
    finding = next(item for item in findings if item["rule_id"] == "RM-SEC-001")
    assert token not in finding["evidence"]


def test_world_writable_chmod_and_unsafe_extractall():
    assert "RM-FILE-002" in _rules("import os\nos.chmod(path, 0o777)\n")
    assert "RM-FILE-001" in _rules("import tarfile\ntarfile.open(p).extractall(dest)\n")
    assert "RM-FILE-001" not in _rules("import tarfile\ntarfile.open(p).extractall(dest, filter='data')\n")


def test_dynamic_path_written_is_low_severity():
    finding = next(i for i in _findings("def save(p, data):\n    open(p, 'w').write(data)\n") if i["rule_id"] == "RM-FILE-003")
    assert finding["severity"] == "low"


def test_style_findings_are_informational():
    rules = {item["rule_id"]: item for item in _findings("print('hi')\nif value == None:\n    pass\n")}
    assert rules["STY-001"]["severity"] == "info"
    assert rules["STY-002"]["severity"] == "info"
    assert rules["STY-001"]["legacy_rule"] == "print-call"


def test_assert_is_flagged_in_application_code_but_not_tests():
    assert "RM-QUAL-003" in _rules("def f(x):\n    assert x > 0\n", "app/logic.py")
    assert "RM-QUAL-003" not in _rules("def test_f():\n    assert 1 == 1\n", "tests/test_logic.py")


def test_complexity_thresholds_create_medium_and_high_findings():
    from app.extractor import extract_structure

    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(16))
    source = f"def busy(x):\n{branches}\n    return -1\n"
    tree = ast.parse(source)
    structure = extract_structure(tree, "app/busy.py")
    findings = analyze_risks(tree, "app/busy.py", source.splitlines(), structure["symbols"])
    complexity = [item for item in findings if item["rule_id"] == "RM-QUAL-001"]
    assert complexity and complexity[0]["severity"] == "medium"


def test_findings_are_sorted_by_severity_and_have_stable_ids():
    source = "print('x')\nimport subprocess\nsubprocess.run(c, shell=True)\n"
    first = _findings(source)
    second = _findings(source)
    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert first[0]["severity"] == "high"
    assert first[-1]["severity"] == "info"


def test_summary_counts_by_severity_category_and_rule():
    summary = summarize_findings(_findings("import subprocess\nsubprocess.run(c, shell=True)\nprint(1)\n"))
    assert summary["total"] == 2
    assert summary["by_severity"]["high"] == 1
    assert summary["by_rule"]["RM-SEC-002"] == 1


def test_credentials_in_test_files_are_low_severity():
    source = 'API_TOKEN = "fake-test-token-value-123"\n'
    tree = ast.parse(source)
    findings = analyze_risks(tree, "tests/test_auth.py", source.splitlines(), symbols=[])
    credential = next(item for item in findings if item["rule_id"] == "RM-SEC-001")
    assert credential["severity"] == "low"
    production = analyze_risks(tree, "app/auth.py", source.splitlines(), symbols=[])
    assert next(item for item in production if item["rule_id"] == "RM-SEC-001")["severity"] == "high"
