"""Ed25519-signed proof receipts. A receipt says: this exact code (by hash) got this verdict under this policy."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_KEY = Path(".boxmatrix") / "receipt_key.pem"


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Signer:
    def __init__(self, key_path: Path = DEFAULT_KEY):
        key_path = Path(key_path)
        if key_path.is_file():
            self.key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key = Ed25519PrivateKey.generate()
            key_path.write_bytes(self.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            os.chmod(key_path, 0o600)
        raw = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public_b64 = base64.b64encode(raw).decode()

    def sign(self, payload: dict) -> dict:
        sig = self.key.sign(canonical(payload))
        return {"payload": payload, "signature": base64.b64encode(sig).decode(), "public_key": self.public_b64}


def verify(receipt: dict, code: str | None = None, public_key_b64: str | None = None) -> tuple[bool, str]:
    """Check the signature (and optionally that `code` matches the hash inside). Pin `public_key_b64` to trust one signer."""
    pub = public_key_b64 or receipt.get("public_key", "")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(
            base64.b64decode(receipt["signature"]), canonical(receipt["payload"]))
    except (InvalidSignature, ValueError, KeyError):
        return False, "bad signature"
    if code is not None and sha256(code) != receipt["payload"].get("code_sha256"):
        return False, "code does not match receipt hash"
    return True, "ok"


def make_payload(res, policy: dict | None) -> dict:
    last = res.verdicts[-1] if res.verdicts else {}
    return {
        "version": 1, "model": res.model, "task_id": res.task_id, "status": res.status,
        "code_sha256": sha256(res.code), "gate_verdict": last.get("verdict", "none"),
        "violations_last_attempt": last.get("violations", []), "attempts": res.attempts,
        "policy_sha256": sha256(json.dumps(policy or {}, sort_keys=True)),
        "tests_passed": res.passed, "tests_total": res.total, "cost_usd": round(res.cost, 6),
        "sandbox_seconds": round(res.sandbox_seconds, 2), "issued_at": int(time.time()),
    }
