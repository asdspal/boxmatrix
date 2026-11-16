from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

# USD per hour, from the GMI Console AgentBox pricing page (Early Access, Nov 2026).
SANDBOX_PRICE_PER_HOUR = {"gmi.sandbox.small": 0.0861, "gmi.sandbox.medium": 0.17, "gmi.sandbox.large": 0.34}
DEFAULT_MODELS = ("deepseek-ai/DeepSeek-V4-Flash", "zai-org/GLM-5.3-Flash", "openai/gpt-6-luna")
MOCK_MODELS = ("mock/reliable", "mock/sloppy", "mock/hostile")


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: str | Path) -> None:
    """Minimal KEY=VALUE loader. Existing environment variables win. Never prints values."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    mock: bool
    inference_key: str = ""
    compute_key: str = ""
    template_id: str = ""
    idc_name: str = "us-central-iowa16"
    product: str = "gmi.sandbox.small"
    budget_usd: float = 1.0
    sandbox_ttl_s: int = 120
    models: tuple = DEFAULT_MODELS
    workers: int = 3


def load_settings(mock: bool, **overrides) -> Settings:
    e = os.environ
    models = tuple(m.strip() for m in e.get("BOXMATRIX_MODELS", "").split(",") if m.strip())
    s = Settings(
        mock=mock,
        inference_key=e.get("GMI_INFERENCE_API_KEY") or e.get("GMI_API_KEY", ""),
        compute_key=e.get("GMI_COMPUTE_API_KEY") or e.get("GMI_API_KEY", ""),
        template_id=e.get("GMI_TEMPLATE_ID", ""),
        idc_name=e.get("GMI_IDC_NAME", "us-central-iowa16"),
        product=e.get("GMI_SANDBOX_PRODUCT", "gmi.sandbox.small"),
        budget_usd=float(e.get("BOXMATRIX_BUDGET_USD", "1.0")),
        models=models or (MOCK_MODELS if mock else DEFAULT_MODELS),
    )
    overrides = {k: v for k, v in overrides.items() if v is not None}
    if overrides:
        s = replace(s, **overrides)
    if s.product not in SANDBOX_PRICE_PER_HOUR:
        raise ConfigError(f"unknown sandbox product {s.product!r}; known: {sorted(SANDBOX_PRICE_PER_HOUR)}")
    if not mock:
        missing = [n for n, v in (("GMI_INFERENCE_API_KEY", s.inference_key), ("GMI_COMPUTE_API_KEY", s.compute_key),
                                  ("GMI_TEMPLATE_ID", s.template_id)) if not v]
        if missing:
            raise ConfigError("missing for live mode: " + ", ".join(missing))
    return s
