from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .runner import CellResult

PASS_THRESHOLD = 0.8


def summarize(results: list[CellResult]) -> list[dict]:
    by = defaultdict(list)
    for r in results:
        by[r.model].append(r)
    rows = []
    for model, rs in by.items():
        ran = [r for r in rs if r.status != "skipped_budget"]
        passes = sum(r.status == "pass" for r in rs)
        cost = sum(r.cost for r in rs)
        rows.append({
            "model": model, "cells": len(rs), "pass": passes,
            "pass_rate": passes / len(ran) if ran else 0.0,
            "blocked": sum(r.status == "blocked" for r in rs),
            "healed": sum(r.status in ("pass", "fail") and r.attempts > 1 for r in rs),
            "errors": sum(r.status == "error" for r in rs),
            "skipped": sum(r.status == "skipped_budget" for r in rs),
            "cost_usd": round(cost, 6),
            "cost_per_pass_usd": round(cost / passes, 6) if passes else None,
            "tokens": sum(r.prompt_tokens + r.completion_tokens for r in rs),
        })
    return sorted(rows, key=lambda x: (-x["pass_rate"], x["cost_usd"]))


def recommend(rows: list[dict], threshold: float = PASS_THRESHOLD) -> dict | None:
    ok = [r for r in rows if r["pass_rate"] >= threshold and r["cost_per_pass_usd"] is not None]
    return min(ok, key=lambda r: r["cost_per_pass_usd"]) if ok else None


def to_markdown(results: list[CellResult], rows: list[dict], meta: dict) -> str:
    best = recommend(rows)
    lines = [f"# BoxMatrix report ({meta['mode']})", "",
             f"- suite: {meta.get('suite', 'standard')}  tasks: {meta['tasks']}  models: {len(rows)}  chaos: {meta['chaos']}",
             f"- total spend: ${meta['spent_usd']:.4f} of ${meta['budget_usd']:.2f} cap", "",
             "| model | pass | pass rate | blocked by Z3 | healed by repair | errors | cost USD | USD per pass |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cpp = f"{r['cost_per_pass_usd']:.5f}" if r["cost_per_pass_usd"] is not None else "n/a"
        lines.append(f"| {r['model']} | {r['pass']}/{r['cells']} | {r['pass_rate']:.0%} | {r['blocked']} | "
                     f"{r['healed']} | {r['errors']} | {r['cost_usd']:.5f} | {cpp} |")
    lines += ["", f"**Cheapest model with pass rate >= {PASS_THRESHOLD:.0%}:** "
              + (f"`{best['model']}` at ${best['cost_per_pass_usd']:.5f} per passing task" if best else "none"), "",
              "## Cells", "", "| model | task | status | tests | attempts | violations | gate ms |", "|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: (x.model, x.task_id)):
        lines.append(f"| {r.model} | {r.task_id} | {r.status} | {r.passed}/{r.total} | {r.attempts} | "
                     f"{', '.join(r.violations) or '-'} | {r.gate_ms} |")
    return "\n".join(lines) + "\n"


def write_reports(results: list[CellResult], meta: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = summarize(results)
    md, js = out_dir / "report.md", out_dir / "report.json"
    md.write_text(to_markdown(results, rows, meta))
    js.write_text(json.dumps({"meta": meta, "summary": rows, "recommendation": recommend(rows),
                              "cells": [r.__dict__ for r in results]}, indent=2))
    return md, js
