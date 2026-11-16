"""Test harness source. It is shipped as text into the sandbox and run there with python3 -I."""

HARNESS = r'''import json, runpy, sys
cases = json.load(open("cases.json"))
res = {"passed": 0, "total": len(cases["cases"]), "errors": []}
try:
    ns = runpy.run_path("solution.py")
    fn = ns[cases["entrypoint"]]
except Exception as e:
    res["errors"].append(f"load: {type(e).__name__}: {e}")
    print(json.dumps(res)); sys.exit(0)
for i, c in enumerate(cases["cases"]):
    try:
        got = fn(*c["args"])
        if got == c["expected"]:
            res["passed"] += 1
        else:
            res["errors"].append(f"case {i}: expected {c['expected']!r} got {got!r}")
    except Exception as e:
        res["errors"].append(f"case {i}: {type(e).__name__}: {e}")
print(json.dumps(res))
'''
