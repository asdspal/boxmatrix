"""Pick the LLM client, per-model pricing and sandbox factory for mock or live mode."""
from __future__ import annotations

from .config import ConfigError, Settings
from .gmi import InferenceClient, Sandbox
from .mock import MOCK_PRICING, LocalSandbox, MockLLM


def build_backends(s: Settings, policy: dict | None):
    """Return (llm, pricing_by_model, sandbox_factory). Raises ConfigError on unknown live models."""
    if s.mock:
        return MockLLM(), {m: MOCK_PRICING for m in s.models}, LocalSandbox
    llm = InferenceClient(s.inference_key)
    cat = llm.models()
    missing = [m for m in s.models if m not in cat]
    if missing:
        raise ConfigError(f"unknown models: {missing}")
    hosts = (policy or {}).get("allowed_hosts", [])

    def factory():
        return Sandbox(s.compute_key, s.template_id, s.idc_name, s.sandbox_ttl_s, hosts)

    return llm, {m: cat[m]["pricing"] for m in s.models}, factory
