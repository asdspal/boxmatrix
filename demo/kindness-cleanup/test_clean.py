import csv
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent


def run(csv_name, enrich=None):
    out = tempfile.mkdtemp()
    cmd = [sys.executable, "-I", str(HERE / "clean_resources.py"), str(HERE / csv_name), "--out", out]
    if enrich:
        f = pathlib.Path(out) / "e.json"
        f.write_text(json.dumps(enrich))
        cmd += ["--enrich", str(f)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout), pathlib.Path(out)


def test_starter_sample_seven_rows_become_four():
    summary, out = run("sample_resources.csv")
    assert summary == {"rows_in": 7, "rows_out": 4, "removed": 2, "needs_review": 1}
    rows = list(csv.DictReader(open(out / "cleaned_resources.csv")))
    assert [r["name"] for r in rows] == ["Welcome Guide", "Contributing Checklist", "Sample Notebook", "Office Hours"]
    assert rows[0]["start_here"] == "yes"


def test_messy_list_rules():
    summary, out = run("messy_resources.csv")
    assert summary["rows_out"] == 17 and summary["needs_review"] == 0
    rows = {r["name"]: r for r in csv.DictReader(open(out / "cleaned_resources.csv"))}
    assert rows["Python Basics Video"]["url"] == "https://example.org/python-basics"  # tracking removed, https preferred
    assert rows["Mentorship Program"]["url"] == "https://example.org/mentors"
    assert "Style Guide" not in rows and "Broken Resource" not in rows


def test_model_hint_used_only_for_unknown_category():
    _, out = run("sample_resources.csv", {"welcomeguide": {"category": "Tools", "tip": "Say hi."}})
    rows = {r["name"]: r for r in csv.DictReader(open(out / "cleaned_resources.csv"))}
    assert rows["Welcome Guide"]["category"] == "Getting Started" and rows["Welcome Guide"]["newcomer_tip"] == "Say hi."


def test_script_is_proven_safe_by_z3_gate():
    from boxmatrix.gate import prove
    from boxmatrix.policy import load_policy
    v = prove((HERE / "clean_resources.py").read_text(), load_policy(HERE / "policy.toml"))
    assert v["verdict"] == "unsat_proven_safe"


