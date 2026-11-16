import pytest

from boxmatrix.attacks import ATTACKS
from boxmatrix.gate import prove

SAFE = "import math\n\ndef f(x):\n    return math.floor(x) + 1\n"


def test_safe_code_is_proven():
    v = prove(SAFE)
    assert v["verdict"] == "unsat_proven_safe"
    assert v["violations"] == []


def test_syntax_error_is_blocked():
    assert prove("def (:")["verdict"] == "syntax_error"


@pytest.mark.parametrize("name", list(ATTACKS))
def test_every_attack_is_blocked_with_expected_rule(name):
    code, rule = ATTACKS[name]
    v = prove(code)
    assert v["verdict"] == "sat_violation_found", name
    assert rule in v["violations"], (name, v["violations"])


def test_gate_is_fast():
    assert prove(SAFE)["solve_ms"] < 500


def test_regex_compile_is_fine_but_bare_compile_is_not():
    assert prove("import re\nP = re.compile('a+')\n")["verdict"] == "unsat_proven_safe"
    assert prove("def f(s):\n    return compile(s, 'x', 'exec')\n")["verdict"] == "sat_violation_found"
    assert prove("import builtins\nbuiltins.compile('1', 'x', 'eval')\n")["verdict"] == "sat_violation_found"
