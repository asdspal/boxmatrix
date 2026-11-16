"""Clean a messy resource CSV inside a GMI AgentBox v2 sandbox.

1. A GMI model (openai/gpt-6-luna) suggests a category, a friendly one-line tip and a level for each row.
2. The Z3 gate from BoxMatrix proves the cleanup script safe (no network, no processes, no eval).
3. A fresh sandbox is created, the CSV, the model hints and the script are uploaded, the script runs, results are downloaded.
4. The sandbox is deleted and checked.

Usage: python run_kindness.py messy_resources.csv --out results/messy
"""
import argparse
import csv
import json
import re
import time
from pathlib import Path

import httpx

from boxmatrix.config import load_dotenv, load_settings
from boxmatrix.cost import sandbox_cost, token_cost
from boxmatrix.gate import prove
from boxmatrix.gmi import GMIError, InferenceClient, Sandbox
from boxmatrix.policy import load_policy

MODEL = "openai/gpt-6-luna"
HERE = Path(__file__).parent
OUTPUTS = ["cleaned_resources.csv", "NEWCOMER_GUIDE.md", "needs_review.csv", "cleaning_report.md"]
SYSTEM = (
    "You help a community welcome newcomers. You get a JSON list of resources with fields id, name, category, description. "
    "Reply with ONLY a JSON list. For every id return: id, category (exactly one of: Getting Started, Tutorials, Events, "
    "Community, Tools, Reference), tip (one warm sentence under 110 characters that says why a newcomer would want it. "
    "Do NOT start with the resource name: start with a verb such as Learn, Ask, Join, Find or Try. Use ONLY the given name "
    "and description, never invent facts, no links; if the description is empty keep the tip short and generic), "
    "level (one of: beginner, any, intermediate)."
)


def name_key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def ask_model(llm, pricing, rows):
    payload = [{"id": i, "name": r["name"].strip(), "category": r["category"].strip(), "description": r["description"].strip()}
               for i, r in enumerate(rows) if r["name"].strip()]
    r = llm.chat(MODEL, SYSTEM, json.dumps(payload), 4096)
    text = re.sub(r"^```(?:json)?|```$", "", r.text.strip(), flags=re.M).strip()
    hints = {}
    for item in json.loads(text):
        row = rows[int(item["id"])]
        hints.setdefault(name_key(row["name"]), {"category": item.get("category", ""), "tip": str(item.get("tip", ""))[:140],
                                                  "level": item.get("level", "")})
    return hints, token_cost(pricing, r.prompt_tokens, r.completion_tokens), r.latency_ms


def put(sb, remote, data):
    r = httpx.post(f"{sb.host}/files", params={"path": remote}, headers=sb.dh, files={"file": (Path(remote).name, data)}, timeout=60)
    if r.status_code != 200:
        raise GMIError(f"upload {remote}: http {r.status_code} {r.text[:200]}")


def get(sb, remote):
    r = httpx.get(f"{sb.host}/files", params={"path": remote}, headers=sb.dh, timeout=60)
    if r.status_code != 200:
        raise GMIError(f"download {remote}: http {r.status_code}")
    return r.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="results/run")
    a = ap.parse_args()
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parents[1] / ".env")  # repo root
    load_dotenv(HERE.parents[2] / ".env")  # a shared .env one level above the repo, if you keep one
    s = load_settings(mock=False)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    source = Path(a.csv)
    with open(source, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"input: {source.name}, {len(rows)} rows")

    llm = InferenceClient(s.inference_key)
    pricing = llm.models()[MODEL]["pricing"]
    hints, llm_cost, ms = ask_model(llm, pricing, rows)
    print(f"model {MODEL}: hints for {len(hints)} rows in {ms} ms, cost ${llm_cost:.5f}")

    script = (HERE / "clean_resources.py").read_text()
    verdict = prove(script, load_policy(HERE / "policy.toml"))
    print(f"Z3 gate: {verdict['verdict']} in {verdict['solve_ms']} ms")
    if verdict["verdict"] != "unsat_proven_safe":
        raise SystemExit(f"refusing to run: {verdict['violations']}")

    t0 = time.monotonic()
    with Sandbox(s.compute_key, s.template_id, s.idc_name, 180) as sb:
        print(f"sandbox {sb.id[:8]}... running (egress closed)")
        put(sb, "/tmp/work/clean_resources.py", script.encode())
        put(sb, "/tmp/work/input.csv", source.read_bytes())
        put(sb, "/tmp/work/enrich.json", json.dumps(hints).encode())
        res = sb.exec("cd /tmp/work && mkdir -p out && python3 -I clean_resources.py input.csv --enrich enrich.json --out out", 60)
        print("sandbox stdout:", res.stdout.strip(), "| exit", res.exit_code)
        if res.exit_code != 0:
            raise SystemExit(f"cleanup failed in sandbox: {res.stderr[-300:]}")
        for name in OUTPUTS:
            (out / name).write_bytes(get(sb, f"/tmp/work/out/{name}"))
        secs = sb.seconds_alive
    total = llm_cost + sandbox_cost(s.product, secs)
    print(f"sandbox deleted. alive {secs:.1f}s, total cost about ${total:.5f}")
    (out / "run.json").write_text(json.dumps({"model": MODEL, "rows_in": len(rows), "gate": verdict["verdict"],
                                              "sandbox_seconds": round(secs, 1), "cost_usd": round(total, 6),
                                              "sandbox_result": json.loads(res.stdout.strip().splitlines()[-1])}, indent=2))
    print(f"results in {out}/ (wall {time.monotonic() - t0:.1f}s)")


main()
