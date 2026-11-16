# Kindness cleanup (GMI weekly challenge)

Turns a messy community resource list into a welcome guide for newcomers, inside a GMI AgentBox v2 sandbox.

```
# from the repo root, one time:
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
cd demo/kindness-cleanup
python3 clean_resources.py sample_resources.csv --out /tmp/out   # local, no model, free
python run_kindness.py messy_resources.csv --out results/messy   # model + Z3 gate + sandbox (about $0.001)
pytest -q test_clean.py
```
Live mode needs a `.env` (here or in the repo root; copy `.env.example`) (GMI keys and `GMI_TEMPLATE_ID` of a python3 template). Delete it afterwards.
Flow: model hints (host) -> Z3 gate proves the script safe under `policy.toml` -> upload CSV, hints and script to a fresh sandbox
(egress closed) -> run -> download results -> delete sandbox.
`sample_resources.csv` is a 7-row reconstruction of the starter kit sample; `messy_resources.csv` is a 24-row harder list. Swap in your own CSV
(columns: name,url,category,description).
