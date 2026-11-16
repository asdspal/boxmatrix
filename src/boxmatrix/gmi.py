"""GMI clients: OpenAI-compatible inference and AgentBox sandboxes. httpx only."""
from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass

import httpx

UA = {"User-Agent": "boxmatrix/0.1 (+https://github.com)"}  # Cloudflare 1010 blocks default python UAs
INFER_URL = "https://api.gmi-serving.com/v1"
CONTROL_URL = "https://console.gmicloud.ai/api/v2"


class GMIError(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class InferenceClient:
    def __init__(self, api_key: str, base_url: str = INFER_URL):
        self.h = {**UA, "Authorization": f"Bearer {api_key}"}
        self.base = base_url

    def models(self) -> dict:
        r = httpx.get(f"{self.base}/models", headers=self.h, timeout=30)
        r.raise_for_status()
        return {m["id"]: m for m in r.json()["data"]}

    def chat(self, model: str, system: str, user: str, max_tokens: int = 2048) -> ChatResult:
        t0 = time.monotonic()
        r = httpx.post(f"{self.base}/chat/completions", headers=self.h, timeout=120, json={
            "model": model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if r.status_code != 200:
            raise GMIError(f"chat {model}: http {r.status_code} {r.text[:200]}")
        d = r.json()
        u = d.get("usage") or {}
        text = (d["choices"][0]["message"].get("content") or "")
        return ChatResult(text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                          int((time.monotonic() - t0) * 1000))


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    status: str


class Sandbox:
    """One AgentBox sandbox. Use as a context manager so delete always runs."""

    def __init__(self, api_key: str, template_id: str, idc_name: str, ttl_s: int = 120,
                 egress_allow: list[str] | None = None, control_url: str = CONTROL_URL):
        self.h = {**UA, "Authorization": f"Bearer {api_key}"}
        self.control, self.tpl, self.idc, self.ttl = control_url, template_id, idc_name, ttl_s
        self.egress_allow = egress_allow or []
        self.id = self.host = self.dh = None
        self.created_at = 0.0

    def __enter__(self) -> Sandbox:
        body = {"template_id": self.tpl, "idc_name": self.idc, "timeout": self.ttl,
                "egress_control": True, "egress": {"allowed_hostnames": self.egress_allow},
                "metadata": {"app": "boxmatrix"}}
        r = httpx.post(f"{self.control}/sandboxes", json=body, timeout=60,
                       headers={**self.h, "Idempotency-Key": str(uuid.uuid4())})
        if r.status_code != 201:
            raise GMIError(f"create sandbox: http {r.status_code} {r.text[:300]}")
        d = r.json()["data"]
        self.id, self.created_at = d["id"], time.monotonic()
        self.host = f"https://{d['sandbox_key']}.{d['domain']}"
        self.dh = {**UA, "X-Access-Token": d["sandbox_access_token"]}
        for _ in range(60):
            g = httpx.get(f"{self.control}/sandboxes/{self.id}", headers=self.h, timeout=30).json()
            state = g.get("data", {}).get("state")
            if state == "running":
                return self
            if state == "failed":
                raise GMIError(f"sandbox failed: {g}")
            time.sleep(1)
        raise GMIError("sandbox did not reach running in 60s")

    def __exit__(self, *exc) -> None:
        if self.id:
            try:
                httpx.delete(f"{self.control}/sandboxes/{self.id}", headers=self.h, timeout=30)
            except httpx.HTTPError:
                pass  # TTL (`timeout`) is the backstop

    @property
    def seconds_alive(self) -> float:
        return time.monotonic() - self.created_at

    def exec(self, command: str, timeout_s: int = 30) -> ExecResult:
        r = httpx.post(f"{self.host}/executions", params={"wait": "true", "wait_timeout_seconds": 20},
                       headers=self.dh, timeout=60, json={"action": "exec", "parameters": {
                           "command": command, "execution_timeout_seconds": timeout_s}})
        if r.status_code not in (200, 202):
            raise GMIError(f"exec: http {r.status_code} {r.text[:300]}")
        d = r.json()
        deadline = time.monotonic() + timeout_s + 10
        while d.get("status") in ("pending", "running", "cancelling") and time.monotonic() < deadline:
            time.sleep(1)
            d = httpx.get(f"{self.host}/executions/{d['execution_id']}", headers=self.dh, timeout=30).json()
        return ExecResult(d.get("exit_code"), d.get("stdout") or "", d.get("stderr") or "", d.get("status", "unknown"))

    def run_python_case(self, solution: str, harness: str, cases: dict, timeout_s: int = 30) -> ExecResult:
        """Ship solution, harness and cases in ONE exec as base64, then run the harness."""
        enc = lambda s: base64.b64encode(s.encode()).decode()
        cmd = ("mkdir -p /tmp/bm && cd /tmp/bm && "
               f"echo {enc(solution)} | base64 -d > solution.py && "
               f"echo {enc(harness)} | base64 -d > harness.py && "
               f"echo {enc(json.dumps(cases))} | base64 -d > cases.json && "
               "python3 -I harness.py")
        return self.exec(cmd, timeout_s)


def cleanup_sandboxes(api_key: str, everything: bool = False, control_url: str = CONTROL_URL) -> int:
    """Delete leftover BoxMatrix sandboxes (metadata app=boxmatrix). `everything=True` deletes all of them."""
    h = {**UA, "Authorization": f"Bearer {api_key}"}
    r = httpx.get(f"{control_url}/sandboxes", headers=h, timeout=30)
    r.raise_for_status()
    n = 0
    for item in r.json().get("items", []):
        if everything or (item.get("metadata") or {}).get("app") == "boxmatrix":
            httpx.delete(f"{control_url}/sandboxes/{item['id']}", headers=h, timeout=30)
            n += 1
    return n
