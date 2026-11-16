---
name: boxmatrix
description: Compare cheap GMI Cloud models on a coding task suite. Each model's code is Z3-proven safe, then run in an isolated GMI AgentBox sandbox. Use when asked which model is cheapest for a task, or to run BoxMatrix.
---

# BoxMatrix

1. Run `boxmatrix run --mock` first. It is free and offline. Confirm it exits 0.
2. For a live run, confirm `.env` exists (never print it), then run
   `boxmatrix run --tasks 3 --budget 0.25`. Raise only if the user agrees.
3. Read `reports/latest/report.md`. Quote the recommended model and the USD-per-pass column.
4. If a run was interrupted, run `boxmatrix cleanup` so no sandbox keeps billing.
5. Never edit `gate.py` rules to make a model pass. A `blocked` cell is a correct result.
