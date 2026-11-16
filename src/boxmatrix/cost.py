from __future__ import annotations

import threading

from .config import SANDBOX_PRICE_PER_HOUR


class BudgetExceeded(RuntimeError):
    pass


def token_cost(pricing: dict, prompt_tokens: int, completion_tokens: int) -> float:
    """pricing holds USD *per token* as strings, exactly as GET /v1/models returns them."""
    return prompt_tokens * float(pricing.get("prompt") or 0) + completion_tokens * float(pricing.get("completion") or 0)


def sandbox_cost(product: str, seconds: float) -> float:
    return SANDBOX_PRICE_PER_HOUR[product] * max(seconds, 0.0) / 3600.0


class Budget:
    """Thread-safe spend meter with a hard cap. `reserve` is called BEFORE spending."""

    def __init__(self, cap_usd: float):
        self.cap, self.spent, self._lock = cap_usd, 0.0, threading.Lock()

    def reserve(self, estimate_usd: float) -> None:
        with self._lock:
            if self.spent + estimate_usd > self.cap:
                raise BudgetExceeded(f"spent ${self.spent:.4f} + est ${estimate_usd:.4f} > cap ${self.cap:.2f}")

    def charge(self, usd: float) -> None:
        with self._lock:
            self.spent += usd

    @property
    def remaining(self) -> float:
        return self.cap - self.spent
