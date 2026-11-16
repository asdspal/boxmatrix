"""Proof gate: extract capability facts from untrusted Python with `ast`, then let Z3 decide.

Trust boundary: `extract_facts` is the trusted part (plain Python, no LLM). Z3 proves that the
extracted facts cannot reach any bad state defined by the policy. UNSAT = proven safe,
SAT = violation, and the model is the counterexample fed back to the model for repair.
"""
from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass, field

import z3

NET_MODULES = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "ftplib",
               "smtplib", "telnetlib", "asyncio", "aiohttp", "websocket", "websockets"}
PROC_MODULES = {"os", "subprocess", "pty", "ctypes", "multiprocessing", "signal", "shutil",
                "sys", "importlib", "pathlib", "tempfile", "resource", "fcntl", "mmap", "builtins"}
DYNAMIC_CALLS = {"eval", "exec", "compile", "__import__", "globals", "locals", "vars", "input",
                 "breakpoint"}
ESCAPE_ATTRS = {"__class__", "__subclasses__", "__globals__", "__builtins__", "__bases__",
                "__mro__", "__code__", "__closure__", "__dict__", "__getattribute__", "__loader__"}
IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
URL = re.compile(r"(?i)\b(?:https?|ftp|ws)://")
URL_HOST = re.compile(r"(?i)\b(?:https?|ftp|ws)://(?:[^/@\s]*@)?([^/\s:?#]+)")


@dataclass
class Facts:
    imports_net: bool = False
    imports_proc: bool = False
    dynamic_exec: bool = False
    dunder_escape: bool = False
    writes_files: bool = False
    url_literal: bool = False
    ip_literals: list = field(default_factory=list)
    url_hosts: list = field(default_factory=list)
    syntax_error: str = ""
    evidence: dict = field(default_factory=dict)


def _note(f: Facts, key: str, detail: str) -> None:
    f.evidence.setdefault(key, []).append(detail)


def extract_facts(code: str) -> Facts:
    f = Facts()
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        f.syntax_error = f"line {e.lineno}: {e.msg}"
        return f
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                root = n.split(".")[0]
                if root in NET_MODULES:
                    f.imports_net = True
                    _note(f, "imports_net", f"line {node.lineno}: import {n}")
                if root in PROC_MODULES:
                    f.imports_proc = True
                    _note(f, "imports_proc", f"line {node.lineno}: import {n}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            is_regex_compile = (name == "compile" and isinstance(fn, ast.Attribute)
                                and isinstance(fn.value, ast.Name) and fn.value.id == "re")
            if name in DYNAMIC_CALLS and not is_regex_compile:  # re.compile builds a pattern, it does not run code
                f.dynamic_exec = True
                _note(f, "dynamic_exec", f"line {node.lineno}: {name}()")
            if name in {"getattr", "setattr", "delattr"} and len(node.args) >= 2 and not (
                    isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
                    and not node.args[1].value.startswith("__")):
                f.dunder_escape = True
                _note(f, "dunder_escape", f"line {node.lineno}: {name}() with non-literal or dunder name")
            if name == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if not mode or any(c in mode for c in "wax+"):
                    f.writes_files = True
                    _note(f, "writes_files", f"line {node.lineno}: open(mode={mode or 'unknown'!r})")
        elif isinstance(node, ast.Attribute) and node.attr in ESCAPE_ATTRS:
            f.dunder_escape = True
            _note(f, "dunder_escape", f"line {node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in ESCAPE_ATTRS | {"__builtins__"}:
            f.dunder_escape = True
            _note(f, "dunder_escape", f"line {node.lineno}: {node.id}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if URL.search(node.value):
                f.url_literal = True
                _note(f, "url_literal", f"line {node.lineno}: {node.value[:40]!r}")
                f.url_hosts += [h.lower() for h in URL_HOST.findall(node.value)]
            for m in IPV4.finditer(node.value):
                octs = [int(x) for x in m.groups()]
                if all(0 <= o <= 255 for o in octs):
                    f.ip_literals.append(octs)
                    _note(f, "ip_literal", f"line {node.lineno}: {m.group(0)}")
    return f


DEFAULT_POLICY = {"allow_net": False, "allow_proc": False, "allow_file_write": False, "allowed_hosts": []}


def prove(code: str, policy: dict | None = None) -> dict:
    """Return {verdict, solve_ms, violations, counterexample, evidence}.

    verdict: unsat_proven_safe | sat_violation_found | syntax_error | timeout_unknown
    """
    pol = {**DEFAULT_POLICY, **(policy or {})}
    facts = extract_facts(code)
    if facts.syntax_error:
        return {"verdict": "syntax_error", "solve_ms": 0.0, "violations": ["syntax_error"],
                "counterexample": {"syntax_error": facts.syntax_error}, "evidence": {}}
    t0 = time.perf_counter()
    ctx = z3.Context()
    s = z3.Solver(ctx=ctx)
    s.set("timeout", 500)
    B = lambda n: z3.Bool(n, ctx=ctx)
    net, proc, dyn, esc, wr, url = (B(n) for n in
        ("imports_net", "imports_proc", "dynamic_exec", "dunder_escape", "writes_files", "url_literal"))
    for var, val in ((net, facts.imports_net), (proc, facts.imports_proc), (dyn, facts.dynamic_exec),
                     (esc, facts.dunder_escape), (wr, facts.writes_files), (url, facts.url_literal)):
        s.add(var == val)
    ip_var = B("has_ip_literal")
    s.add(ip_var == bool(facts.ip_literals))
    # Every extracted IP literal must avoid the cloud metadata address and private ranges.
    ip_bad = []
    for lit in facts.ip_literals:
        o = [z3.IntVal(x, ctx=ctx) for x in lit]
        meta = z3.And(o[0] == 169, o[1] == 254)
        private = z3.Or(o[0] == 10, o[0] == 127, z3.And(o[0] == 172, o[1] >= 16, o[1] <= 31),
                        z3.And(o[0] == 192, o[1] == 168), z3.And(o[0] == 169, o[1] == 254))
        ip_bad.append(z3.Or(meta, private))
    # With networking allowed, every URL host must be on the allowlist (the same list sets sandbox egress).
    allowed = [z3.StringVal(h.lower(), ctx=ctx) for h in pol["allowed_hosts"]]
    host_bad = []
    for h in facts.url_hosts:
        hv = z3.StringVal(h, ctx=ctx)
        host_bad.append(z3.Not(z3.Or(*[hv == a for a in allowed])) if allowed else z3.BoolVal(True, ctx=ctx))
    rules = {
        "no_network_import": z3.And(net, z3.BoolVal(not pol["allow_net"], ctx=ctx)),
        "no_process_or_fs_module": z3.And(proc, z3.BoolVal(not pol["allow_proc"], ctx=ctx)),
        "no_dynamic_exec": dyn,
        "no_dunder_escape": esc,
        "no_file_write": z3.And(wr, z3.BoolVal(not pol["allow_file_write"], ctx=ctx)),
        "no_url_literal": z3.And(url, z3.BoolVal(not pol["allow_net"], ctx=ctx)),
        "no_unlisted_host": z3.And(z3.BoolVal(bool(pol["allow_net"]), ctx=ctx), z3.Or(*host_bad))
        if host_bad else z3.BoolVal(False, ctx=ctx),
        "no_private_or_metadata_ip": z3.Or(*ip_bad) if ip_bad else z3.BoolVal(False, ctx=ctx),
    }
    flags = {name: z3.Bool(f"bad_{name}", ctx=ctx) for name in rules}
    for name, expr in rules.items():
        s.add(flags[name] == expr)
    s.add(z3.Or(*flags.values()))  # ask Z3: can any bad state hold?
    res = s.check()
    ms = round((time.perf_counter() - t0) * 1000, 2)
    if res == z3.unsat:
        return {"verdict": "unsat_proven_safe", "solve_ms": ms, "violations": [], "counterexample": {}, "evidence": {}}
    if res == z3.sat:
        m = s.model()
        bad = [n for n, fl in flags.items() if z3.is_true(m.eval(fl, model_completion=True))]
        return {"verdict": "sat_violation_found", "solve_ms": ms, "violations": bad,
                "counterexample": {str(d): str(m[d]) for d in m.decls() if not str(d).startswith("bad_")},
                "evidence": facts.evidence}
    return {"verdict": "timeout_unknown", "solve_ms": ms, "violations": ["timeout"], "counterexample": {}, "evidence": {}}
