"""Live dashboard: FastAPI + Server-Sent Events + one static page. One matrix run at a time."""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .backends import build_backends
from .config import DEFAULT_MODELS, ConfigError, load_settings
from .cost import Budget
from .policy import POLICY_DIR, PolicyError, load_policy
from .receipt import Signer, verify
from .report import recommend, summarize
from .runner import run_matrix
from .tasks import load_tasks

WEB = Path(__file__).parent / "web"


class RunRequest(BaseModel):
    mock: bool = True
    suite: str = "standard"
    tasks: int = Field(0, ge=0, le=50)
    models: list[str] = []
    policy: str = "strict.toml"
    budget: float = Field(0.25, gt=0)
    chaos: bool = False
    repairs: int = Field(2, ge=0, le=3)


class VerifyRequest(BaseModel):
    receipt: dict
    code: str | None = None


class Hub:
    """Append-only event log. SSE clients replay it from index 0, so a page refresh restores the matrix."""

    def __init__(self):
        self.events: list[dict] = []
        self.running = False
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.events = []

    def push(self, kind: str, **data):
        with self.lock:
            self.events.append({"type": kind, **data})


def create_app(allow_live: bool = False, max_budget: float = 0.25) -> FastAPI:
    app = FastAPI(title="BoxMatrix")
    hub = Hub()
    signer = Signer()

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/config")
    def config():
        s = load_settings(mock=True)
        return {"allow_live": allow_live, "max_budget": max_budget, "running": hub.running,
                "suites": ["standard", "hard", "redteam", "all"],
                "policies": sorted(p.name for p in POLICY_DIR.glob("*.toml")),
                "live_models": list(DEFAULT_MODELS),
                "mock_models": list(s.models), "public_key": signer.public_b64}

    @app.post("/api/run")
    def start(req: RunRequest):
        if not req.mock and not allow_live:
            raise HTTPException(403, "live mode is off. Start the server with --live.")
        if req.budget > max_budget:
            raise HTTPException(400, f"budget above the server cap of ${max_budget}")
        with hub.lock:
            if hub.running:
                raise HTTPException(409, "a run is already in progress")
            hub.running = True
        try:
            pol = load_policy(req.policy)
            s = load_settings(req.mock, budget_usd=req.budget, models=tuple(req.models) or None)
            task_list = load_tasks(limit=req.tasks or None, suite=req.suite)
            if not task_list:
                raise HTTPException(400, "no tasks in that suite")
            if not req.mock:
                from .config import load_dotenv
                load_dotenv(Path.cwd() / ".env")
                s = load_settings(False, budget_usd=req.budget, models=tuple(req.models) or None)
            llm, pricing, factory = build_backends(s, pol)
        except (ConfigError, PolicyError) as e:
            hub.running = False
            raise HTTPException(400, str(e)) from e
        except HTTPException:
            hub.running = False
            raise
        hub.reset()
        threading.Thread(target=_work, args=(req, s, pol, task_list, llm, pricing, factory), daemon=True).start()
        return {"started": True, "cells": len(task_list) * len(s.models)}

    def _work(req, s, pol, task_list, llm, pricing, factory):
        bud = Budget(req.budget)
        hub.push("start", mode="mock" if req.mock else "live", suite=req.suite, models=list(s.models),
                 tasks=[{"id": t.id, "title": t.title, "suite": t.suite} for t in task_list], budget=req.budget,
                 policy=pol)

        def done(r):
            cell = asdict(r)
            cell["cost"] = r.cost
            hub.push("cell_done", cell=cell, spent=bud.spent)

        try:
            results = run_matrix(task_list, list(s.models), llm, factory, pricing, bud, s, pol, req.repairs, req.chaos,
                                 on_cell=done, signer=signer, on_start=lambda t, m: hub.push("cell_start", task=t.id, model=m))
            rows = summarize(results)
            hub.push("done", summary=rows, recommendation=recommend(rows), spent=bud.spent)
        except Exception as e:  # noqa: BLE001 - surface any failure to the page instead of dying silently
            hub.push("error", message=f"{type(e).__name__}: {e}"[:300])
        finally:
            hub.running = False

    @app.get("/api/events")
    async def events():
        async def stream():
            i = 0
            idle = 0
            while True:
                with hub.lock:
                    batch, i = hub.events[i:], len(hub.events)
                for ev in batch:
                    yield f"data: {json.dumps(ev)}\n\n"
                idle = 0 if batch else idle + 1
                if idle % 50 == 49:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.2)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/verify")
    def verify_receipt(req: VerifyRequest):
        ok, why = verify(req.receipt, req.code)
        return {"ok": ok, "reason": why}

    return app
