import pytest

from boxmatrix.config import ConfigError, load_dotenv, load_settings
from boxmatrix.cost import Budget, BudgetExceeded, sandbox_cost, token_cost
from boxmatrix.tasks import extract_code, load_tasks


def test_token_cost_uses_per_token_strings():
    assert token_cost({"prompt": "0.0000001", "completion": "0.0000005"}, 1000, 100) == pytest.approx(0.00015)


def test_sandbox_cost_hourly():
    assert sandbox_cost("gmi.sandbox.small", 3600) == pytest.approx(0.0861)


def test_budget_blocks_before_spending():
    b = Budget(0.02)
    b.reserve(0.01)
    b.charge(0.015)
    with pytest.raises(BudgetExceeded):
        b.reserve(0.01)


def test_extract_code_strips_fences():
    assert extract_code("```python\nx = 1\n```") == "x = 1\n"
    assert extract_code("x = 2") == "x = 2\n"


def test_ten_tasks_with_cases():
    ts = load_tasks()
    assert len(ts) == 10
    assert all(t.cases and t.entrypoint for t in ts)
    assert len(load_tasks(limit=3)) == 3


def test_live_settings_require_keys(monkeypatch):
    for k in ("GMI_INFERENCE_API_KEY", "GMI_COMPUTE_API_KEY", "GMI_API_KEY", "GMI_TEMPLATE_ID"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        load_settings(mock=False)
    assert load_settings(mock=True).models[0].startswith("mock/")


def test_bad_product_rejected():
    with pytest.raises(ConfigError):
        load_settings(mock=True, product="nope")


def test_dotenv_does_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_A", "keep")
    monkeypatch.delenv("BM_B", raising=False)
    f = tmp_path / ".env"
    f.write_text("# c\nBM_A=new\nBM_B='two'\n")
    load_dotenv(f)
    import os
    assert os.environ["BM_A"] == "keep" and os.environ["BM_B"] == "two"
