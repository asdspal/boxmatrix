import json
import time

import pytest
from fastapi.testclient import TestClient

from boxmatrix.config import load_settings
from boxmatrix.cost import Budget
from boxmatrix.gate import prove
from boxmatrix.mock import LocalSandbox, MockLLM
from boxmatrix.policy import PolicyError, load_policy
from boxmatrix.receipt import Signer, verify
from boxmatrix.runner import run_matrix
from boxmatrix.server import create_app
from boxmatrix.tasks import load_tasks

PRICE = {"prompt": "0.0000001", "completion": "0.0000005"}
GMI_OK = 'import urllib.request\ndef f():\n    return urllib.request.urlopen("https://api.gmi-serving.com/v1/models")\n'


def test_suite_sizes():
    assert len(load_tasks(suite="standard")) == 10
    assert len(load_tasks(suite="hard")) == 8
    assert len(load_tasks(suite="redteam")) == 5
    assert len(load_tasks(suite="all")) == 23


def test_every_reference_passes_its_own_cases():
    for t in load_tasks(suite="all"):
        if not t.reference:
            continue
        ns: dict = {}
        exec(t.reference, ns)  # noqa: S102 - trusted repo file
        fn = ns[t.entrypoint]
        assert all(fn(*c["args"]) == c["expected"] for c in t.cases), t.id


def test_tempting_solutions_are_all_blocked_by_gate():
    for t in load_tasks(suite="redteam"):
        assert prove(t.tempting)["verdict"] == "sat_violation_found", t.id
        assert prove(t.reference)["verdict"] == "unsat_proven_safe", t.id


def test_redteam_cells_heal_and_hard_sloppy_fails_some():
    s = load_settings(mock=True)
    res = run_matrix(load_tasks(suite="redteam"), ["mock/reliable"], MockLLM(), LocalSandbox, {"mock/reliable": PRICE},
                     Budget(1), s)
    assert all(r.status == "pass" and r.attempts == 2 for r in res)
    hard = run_matrix(load_tasks(suite="hard"), ["mock/sloppy"], MockLLM(), LocalSandbox, {"mock/sloppy": PRICE},
                      Budget(1), s)
    assert 0 < sum(r.status == "pass" for r in hard) < len(hard)


def test_policy_host_allowlist():
    strict, api = load_policy("strict.toml"), load_policy("gmi-api-only.toml")
    assert prove(GMI_OK, strict)["verdict"] == "sat_violation_found"
    assert prove(GMI_OK, api)["verdict"] == "unsat_proven_safe"
    bad = prove(GMI_OK.replace("api.gmi-serving.com", "evil.example.org"), api)
    assert bad["violations"] == ["no_unlisted_host"]


def test_policy_validation(tmp_path):
    f = tmp_path / "p.toml"
    f.write_text("[policy]\nallowed_hosts = ['a.com']\n")
    with pytest.raises(PolicyError):
        load_policy(f)
    f.write_text("[policy]\nbogus = true\n")
    with pytest.raises(PolicyError):
        load_policy(f)


def test_receipts_sign_verify_and_detect_tampering(tmp_path):
    signer = Signer(tmp_path / "k.pem")
    s = load_settings(mock=True)
    res = run_matrix(load_tasks(limit=2), ["mock/reliable"], MockLLM(), LocalSandbox, {"mock/reliable": PRICE}, Budget(1), s,
                     signer=signer)
    r = res[0]
    assert verify(r.receipt, r.code) == (True, "ok")
    assert verify(r.receipt, r.code + "# x")[0] is False
    forged = json.loads(json.dumps(r.receipt))
    forged["payload"]["tests_passed"] = 99
    assert verify(forged, r.code)[0] is False
    assert Signer(tmp_path / "k.pem").public_b64 == signer.public_b64  # key persists


def test_blocked_cell_still_gets_a_receipt(tmp_path):
    s = load_settings(mock=True)
    res = run_matrix(load_tasks(limit=1), ["mock/hostile"], MockLLM(), LocalSandbox, {"mock/hostile": PRICE}, Budget(1), s,
                     max_repairs=0, signer=Signer(tmp_path / "k.pem"))
    assert res[0].status == "blocked" and res[0].receipt["payload"]["status"] == "blocked"


def test_server_mock_run_and_live_is_refused():
    c = TestClient(create_app(allow_live=False))
    assert c.post("/api/run", json={"mock": False}).status_code == 403
    assert c.post("/api/run", json={"mock": True, "budget": 5}).status_code == 400
    assert c.post("/api/run", json={"mock": True, "suite": "redteam", "tasks": 2}).json()["cells"] == 6
    deadline, done = time.time() + 30, None
    with c.stream("GET", "/api/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:") and '"type": "done"' in line:
                done = json.loads(line[5:])
                break
            assert time.time() < deadline
    assert done and done["recommendation"]["model"].startswith("mock/")
    rc = c.get("/api/config").json()
    assert rc["allow_live"] is False and "strict.toml" in rc["policies"]


def test_empty_model_reply_is_never_proven_safe():
    from boxmatrix.cegis import generate_verified
    from boxmatrix.gmi import ChatResult

    class Empty:
        def chat(self, *a, **k):
            return ChatResult("", 10, 4096, 1)

    g = generate_verified(Empty(), "m", load_tasks(limit=1)[0], max_repairs=1)
    assert g.blocked and [v["verdict"] for v in g.verdicts] == ["empty_response"] * 2
