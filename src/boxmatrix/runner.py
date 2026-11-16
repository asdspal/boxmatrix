from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from .cegis import generate_verified
from .config import Settings
from .cost import Budget, BudgetExceeded, sandbox_cost, token_cost
from .gmi import GMIError
from .harness import HARNESS
from .receipt import make_payload
from .tasks import Task

CELL_COST_ESTIMATE_USD = 0.01  # reserved before each cell; real spend is charged afterwards


@dataclass
class CellResult:
    model: str
    task_id: str
    status: str  # pass | fail | blocked | error | skipped_budget
    passed: int = 0
    total: int = 0
    attempts: int = 0
    violations: list = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_cost: float = 0.0
    sandbox_cost: float = 0.0
    sandbox_seconds: float = 0.0
    gate_ms: float = 0.0
    llm_latency_ms: int = 0
    detail: str = ""
    code: str = ""
    verdicts: list = field(default_factory=list)
    receipt: dict = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return self.llm_cost + self.sandbox_cost


def run_cell(task: Task, model: str, llm, sandbox_factory, pricing: dict, budget: Budget, settings: Settings,
             policy: dict | None = None, max_repairs: int = 2, chaos: bool = False, signer=None) -> CellResult:
    res = CellResult(model=model, task_id=task.id, status="error", total=len(task.cases))
    try:
        return _run_cell(res, task, model, llm, sandbox_factory, pricing, budget, settings, policy, max_repairs, chaos)
    finally:
        if signer and res.status != "skipped_budget":
            res.receipt = signer.sign(make_payload(res, policy))


def _run_cell(res, task, model, llm, sandbox_factory, pricing, budget, settings, policy, max_repairs, chaos) -> CellResult:
    try:
        budget.reserve(CELL_COST_ESTIMATE_USD)
    except BudgetExceeded as e:
        res.status, res.detail = "skipped_budget", str(e)
        return res
    try:
        gen = generate_verified(llm, model, task, policy, max_repairs, chaos)
        res.attempts = len(gen.verdicts)
        res.code, res.verdicts = gen.code, gen.verdicts
        res.prompt_tokens, res.completion_tokens, res.llm_latency_ms = gen.prompt_tokens, gen.completion_tokens, gen.latency_ms
        res.llm_cost = token_cost(pricing, gen.prompt_tokens, gen.completion_tokens)
        res.gate_ms = round(sum(v["solve_ms"] for v in gen.verdicts), 2)
        budget.charge(res.llm_cost)
        if gen.blocked:  # fail closed: no sandbox is ever created for unproven code
            res.status = "blocked"
            res.violations = gen.verdicts[-1]["violations"]
            return res
        with sandbox_factory() as sb:
            out = sb.run_python_case(gen.code, HARNESS, task.harness_cases(), timeout_s=20)
            res.sandbox_seconds = sb.seconds_alive
        res.sandbox_cost = sandbox_cost(settings.product, res.sandbox_seconds)
        budget.charge(res.sandbox_cost)
        if out.status == "timed_out" or out.exit_code != 0:
            res.status, res.detail = "fail", f"{out.status} exit={out.exit_code} {out.stderr[-120:]}"
            return res
        import json
        report = json.loads(out.stdout.strip().splitlines()[-1])
        res.passed, res.total = report["passed"], report["total"]
        res.status = "pass" if res.passed == res.total else "fail"
        res.detail = "; ".join(report["errors"][:2])
    except (GMIError, ValueError, KeyError, OSError) as e:
        res.status, res.detail = "error", f"{type(e).__name__}: {e}"[:300]
    return res


def run_matrix(tasks: list[Task], models: list[str], llm, sandbox_factory, pricing_by_model: dict, budget: Budget,
               settings: Settings, policy: dict | None = None, max_repairs: int = 2, chaos: bool = False,
               on_cell=None, signer=None, on_start=None) -> list[CellResult]:
    jobs = [(t, m) for m in models for t in tasks]

    def work(job):
        t, m = job
        if on_start:
            on_start(t, m)
        r = run_cell(t, m, llm, sandbox_factory, pricing_by_model[m], budget, settings, policy, max_repairs, chaos, signer)
        if on_cell:
            on_cell(r)
        return r

    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        return list(pool.map(work, jobs))


def timed(fn, *a, **k):
    t0 = time.monotonic()
    out = fn(*a, **k)
    return out, time.monotonic() - t0


__all__ = ["CellResult", "asdict", "run_cell", "run_matrix"]
