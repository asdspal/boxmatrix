from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .attacks import ATTACKS
from .backends import build_backends
from .config import ConfigError, load_dotenv, load_settings
from .cost import Budget
from .gate import prove
from .gmi import InferenceClient, cleanup_sandboxes
from .policy import load_policy
from .receipt import Signer, verify
from .report import recommend, summarize, write_reports
from .runner import run_matrix
from .tasks import load_tasks

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Proof-gated model matrix on GMI AgentBox.")
console = Console()


@app.callback()
def _env() -> None:
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(Path.cwd().parent / ".env")


@app.command()
def gate(file: Path, allow_net: bool = typer.Option(False, "--allow-net"),
         policy: Path = typer.Option(None, help="TOML policy file (see policies/)")) -> None:
    """Prove a Python file safe before it may run anywhere. Exit code 1 if it is not proven safe."""
    pol = load_policy(policy) if policy else {"allow_net": allow_net}
    v = prove(file.read_text(), pol)
    color = "green" if v["verdict"] == "unsat_proven_safe" else "red"
    console.print(f"[{color}]{v['verdict']}[/{color}] in {v['solve_ms']} ms  violations={v['violations'] or '-'}")
    for rule, items in v["evidence"].items():
        for it in items:
            console.print(f"  - {rule}: {it}")
    raise typer.Exit(0 if v["verdict"] == "unsat_proven_safe" else 1)


@app.command("attack-suite")
def attack_suite() -> None:
    """Every hostile snippet must be blocked, for the expected reason."""
    t = Table("attack", "blocked", "expected rule", "ms")
    failures = 0
    for name, (code, rule) in ATTACKS.items():
        v = prove(code)
        ok = v["verdict"] == "sat_violation_found" and rule in v["violations"]
        failures += not ok
        t.add_row(name, "[green]yes[/green]" if ok else "[red]NO[/red]", rule, str(v["solve_ms"]))
    console.print(t)
    console.print(f"{len(ATTACKS) - failures}/{len(ATTACKS)} attacks blocked")
    raise typer.Exit(1 if failures else 0)


@app.command()
def models(contains: str = typer.Option("", help="substring filter")) -> None:
    """List GMI catalog models with USD per 1M tokens (live)."""
    s = load_settings(mock=False, template_id="x")
    cat = InferenceClient(s.inference_key).models()
    t = Table("model", "in $/1M", "out $/1M")
    for mid, m in sorted(cat.items(), key=lambda kv: float(kv[1]["pricing"]["prompt"] or 0)):
        if contains in mid:
            p = m["pricing"]
            t.add_row(mid, f"{float(p['prompt']) * 1e6:.3f}", f"{float(p['completion']) * 1e6:.3f}")
    console.print(t)


@app.command("check-env")
def check_env() -> None:
    """Verify keys, template and catalog without spending anything."""
    try:
        s = load_settings(mock=False)
    except ConfigError as e:
        console.print(f"[red]FAIL[/red] {e}")
        raise typer.Exit(1)
    cat = InferenceClient(s.inference_key).models()
    missing = [m for m in s.models if m not in cat]
    console.print(f"[green]PASS[/green] inference key ok, {len(cat)} models; missing requested: {missing or 'none'}")
    console.print(f"[green]PASS[/green] left-over sandboxes cleaned: {cleanup_sandboxes(s.compute_key)}")
    raise typer.Exit(1 if missing else 0)


@app.command()
def cleanup(everything: bool = typer.Option(False, "--all")) -> None:
    """Delete leftover sandboxes."""
    s = load_settings(mock=False)
    console.print(f"deleted {cleanup_sandboxes(s.compute_key, everything)} sandbox(es)")


@app.command()
def run(mock: bool = typer.Option(False, "--mock", help="offline, $0"),
        models: str = typer.Option("", help="comma-separated model ids"),
        tasks: int = typer.Option(0, help="limit number of tasks (0 = whole suite)"),
        suite: str = typer.Option("standard", help="standard | hard | redteam | all"),
        policy: Path = typer.Option(None, help="TOML safety policy (default: strict)"),
        budget: float = typer.Option(None, help="hard USD cap"),
        chaos: bool = typer.Option(False, "--chaos", help="ask models to add hostile code"),
        repairs: int = typer.Option(2, help="max Z3-guided repair rounds"),
        workers: int = typer.Option(None),
        out: Path = typer.Option(Path("reports/latest"))) -> None:
    """Generate code with each model, prove it safe with Z3, run it in an isolated sandbox, rank the models."""
    s = load_settings(mock, budget_usd=budget, workers=workers,
                      models=tuple(m for m in models.split(",") if m) or None)
    pol = load_policy(policy) if policy else None
    task_list = load_tasks(limit=tasks or None, suite=suite)
    if not task_list:
        console.print(f"[red]no tasks in suite {suite!r}[/red]")
        raise typer.Exit(2)
    try:
        llm, pricing, factory = build_backends(s, pol)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    bud = Budget(s.budget_usd)
    console.print(f"mode={'mock' if mock else 'LIVE'} models={list(s.models)} tasks={len(task_list)} cap=${bud.cap:.2f}")
    signer = Signer()
    results = run_matrix(task_list, list(s.models), llm, factory, pricing, bud, s, pol, repairs, chaos, signer=signer,
                         on_cell=lambda r: console.print(
                             f"  {r.model:34s} {r.task_id:12s} {r.status:15s} {r.passed}/{r.total} "
                             f"attempts={r.attempts} ${r.cost:.5f} {','.join(r.violations)}"))
    meta = {"mode": "mock" if mock else "live", "suite": suite, "tasks": len(task_list), "chaos": chaos,
            "policy": pol or "strict (default)", "public_key": signer.public_b64,
            "spent_usd": round(bud.spent, 6), "budget_usd": bud.cap}
    md, js = write_reports(results, meta, out)
    rows = summarize(results)
    t = Table("model", "pass", "rate", "blocked", "healed", "errors", "cost $", "$/pass")
    for r in rows:
        t.add_row(r["model"], f"{r['pass']}/{r['cells']}", f"{r['pass_rate']:.0%}", str(r["blocked"]), str(r["healed"]),
                  str(r["errors"]), f"{r['cost_usd']:.5f}", f"{r['cost_per_pass_usd']:.5f}" if r["cost_per_pass_usd"] else "n/a")
    console.print(t)
    best = recommend(rows)
    console.print(f"spent ${bud.spent:.4f} of ${bud.cap:.2f}; recommended: {best['model'] if best else 'none'}")
    console.print(f"wrote {md} and {js}")


@app.command()
def serve(live: bool = typer.Option(False, "--live", help="allow runs that spend money on GMI"),
          max_budget: float = typer.Option(0.25, help="server-side USD cap per run"),
          host: str = "127.0.0.1", port: int = 8765) -> None:
    """Open the live dashboard. Mock mode is free; --live also allows GMI runs under the budget cap."""
    import uvicorn

    from .server import create_app
    console.print(f"dashboard on http://{host}:{port}  live={'ON' if live else 'off'}  cap=${max_budget:.2f}")
    uvicorn.run(create_app(live, max_budget), host=host, port=port, log_level="warning")


@app.command("verify")
def verify_cmd(report: Path = typer.Argument(..., help="report.json written by `boxmatrix run`"),
               public_key: str = typer.Option("", help="pin the signer's public key (base64)")) -> None:
    """Check every receipt signature in a report, and that each receipt matches the code stored next to it."""
    data = json.loads(report.read_text())
    bad = 0
    for cell in data["cells"]:
        rc = cell.get("receipt")
        if not rc:
            continue
        ok, why = verify(rc, cell.get("code", ""), public_key or None)
        bad += not ok
        mark = "[green]ok[/green]" if ok else f"[red]{why}[/red]"
        console.print(f"{cell['model']:34s} {cell['task_id']:14s} {rc['payload']['status']:8s} {mark}")
    console.print(f"{'ALL RECEIPTS VALID' if not bad else str(bad) + ' INVALID'}")
    raise typer.Exit(1 if bad else 0)


if __name__ == "__main__":
    app()
