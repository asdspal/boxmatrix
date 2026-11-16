"""Zero-cost stand-ins for GMI inference and AgentBox so the whole pipeline is testable offline."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time

from .gmi import ChatResult, ExecResult
from .harness import HARNESS
from .mock_data import BUGGY, HOSTILE_PREFIX, REFERENCE
from .tasks import get_task

MOCK_PRICING = {"prompt": "0.00000014", "completion": "0.00000028"}


class MockLLM:
    """Profiles by model name: reliable = always right (after repair); sloppy = wrong on some tasks;
    hostile = emits secret-stealing code on the first attempt and repairs when told why it was blocked."""

    def chat(self, model: str, system: str, user: str, max_tokens: int = 2048) -> ChatResult:
        task_id = user.split("TASK_ID:", 1)[1].split()[0]
        repair = "REPAIR REQUIRED" in user
        task = get_task(task_id)
        safe = REFERENCE.get(task_id) or task.reference
        if model.endswith("hostile") and not repair:
            text = HOSTILE_PREFIX + safe
        elif task.tempting and not repair:
            text = task.tempting  # an eager model takes the unsafe shortcut the prompt hints at
        elif model.endswith("sloppy") and (BUGGY.get(task_id) or task.buggy):
            text = BUGGY.get(task_id) or task.buggy
        else:
            text = safe
        return ChatResult("```python\n" + text + "```", len(user) // 4, len(text) // 4, 5)

    def models(self) -> dict:
        return {m: {"pricing": MOCK_PRICING} for m in ("mock/reliable", "mock/sloppy", "mock/hostile")}


class LocalSandbox:
    """Same interface as gmi.Sandbox, backed by a throwaway temp dir and `python3 -I` with an empty env."""

    def __enter__(self) -> LocalSandbox:
        self.dir, self.t0 = tempfile.mkdtemp(prefix="bm-"), time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    @property
    def seconds_alive(self) -> float:
        return time.monotonic() - self.t0

    def run_python_case(self, solution: str, harness: str, cases: dict, timeout_s: int = 30) -> ExecResult:
        import json
        import pathlib
        d = pathlib.Path(self.dir)
        (d / "solution.py").write_text(solution)
        (d / "harness.py").write_text(harness)
        (d / "cases.json").write_text(json.dumps(cases))
        try:
            p = subprocess.run([sys.executable, "-I", "harness.py"], cwd=d, env={}, capture_output=True,
                               text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return ExecResult(None, "", "timeout", "timed_out")
        return ExecResult(p.returncode, p.stdout, p.stderr, "succeeded" if p.returncode == 0 else "failed")


__all__ = ["HARNESS", "MOCK_PRICING", "LocalSandbox", "MockLLM"]
