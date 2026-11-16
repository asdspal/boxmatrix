"""Spends a few cents on real GMI. Run with: BOXMATRIX_LIVE=1 pytest -m live"""
import os

import pytest

from boxmatrix.config import load_dotenv, load_settings
from boxmatrix.gmi import InferenceClient, Sandbox

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("BOXMATRIX_LIVE") != "1", reason="set BOXMATRIX_LIVE=1")]


def test_inference_lists_models():
    load_dotenv(".env")
    s = load_settings(mock=False)
    assert "deepseek-ai/DeepSeek-V4-Flash" in InferenceClient(s.inference_key).models()


def test_sandbox_roundtrip():
    load_dotenv(".env")
    s = load_settings(mock=False)
    with Sandbox(s.compute_key, s.template_id, s.idc_name, 120) as sb:
        out = sb.exec("python3 -c 'print(6*7)'")
        assert out.exit_code == 0 and out.stdout.strip() == "42"
