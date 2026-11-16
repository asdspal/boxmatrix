"""Safety policy loaded from a TOML file. The same host list feeds the Z3 gate and the sandbox egress allowlist."""
from __future__ import annotations

import tomllib
from pathlib import Path

KEYS = {"allow_net": bool, "allow_proc": bool, "allow_file_write": bool, "allowed_hosts": list}
POLICY_DIR = Path(__file__).parent / "policies"


class PolicyError(ValueError):
    pass


def load_policy(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file() and (POLICY_DIR / p.name).is_file():
        p = POLICY_DIR / p.name
    if not p.is_file():
        raise PolicyError(f"policy file not found: {path}")
    raw = tomllib.loads(p.read_text()).get("policy", {})
    unknown = set(raw) - set(KEYS)
    if unknown:
        raise PolicyError(f"unknown policy keys: {sorted(unknown)}")
    for k, v in raw.items():
        if not isinstance(v, KEYS[k]):
            raise PolicyError(f"policy key {k} must be {KEYS[k].__name__}")
    if raw.get("allowed_hosts") and not raw.get("allow_net"):
        raise PolicyError("allowed_hosts needs allow_net = true")
    return {"allow_net": False, "allow_proc": False, "allow_file_write": False, "allowed_hosts": [], **raw}
