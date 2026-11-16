import json

from boxmatrix.config import load_settings
from boxmatrix.cost import Budget
from boxmatrix.mock import LocalSandbox, MockLLM
from boxmatrix.report import recommend, summarize, write_reports
from boxmatrix.runner import run_matrix
from boxmatrix.tasks import load_tasks

PRICE = {"prompt": "0.0000001", "completion": "0.0000005"}


def _run(models, budget=1.0, chaos=False, repairs=2):
    s = load_settings(mock=True)
    created = []

    def factory():
        sb = LocalSandbox()
        created.append(sb)
        return sb

    res = run_matrix(load_tasks(), models, MockLLM(), factory, {m: PRICE for m in models}, Budget(budget), s,
                     None, repairs, chaos)
    return res, created


def test_reliable_model_passes_everything():
    res, _ = _run(["mock/reliable"])
    assert all(r.status == "pass" for r in res)


def test_hostile_model_is_healed_by_z3_repair():
    res, _ = _run(["mock/hostile"])
    assert all(r.status == "pass" and r.attempts == 2 for r in res)


def test_fail_closed_no_sandbox_when_no_repairs():
    res, created = _run(["mock/hostile"], repairs=0)
    assert all(r.status == "blocked" for r in res)
    assert created == []


def test_sloppy_model_fails_some_tests():
    res, _ = _run(["mock/sloppy"])
    assert 0 < sum(r.status == "pass" for r in res) < len(res)


def test_budget_cap_skips_cells():
    res, _ = _run(["mock/reliable"], budget=0.0)
    assert all(r.status == "skipped_budget" for r in res)


def test_report_files_and_recommendation(tmp_path):
    res, _ = _run(["mock/reliable", "mock/sloppy"])
    rows = summarize(res)
    assert recommend(rows)["model"] == "mock/reliable"
    md, js = write_reports(res, {"mode": "mock", "tasks": 10, "chaos": False, "spent_usd": 0, "budget_usd": 1}, tmp_path)
    assert "BoxMatrix report" in md.read_text()
    assert json.loads(js.read_text())["recommendation"]["model"] == "mock/reliable"
