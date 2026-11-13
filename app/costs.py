"""Turn token usage into money, so the daily cap and the digest can count it."""
from __future__ import annotations

from dataclasses import dataclass

from .config import PRICES_PER_MTOK


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens

    def as_dict(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens, "cache_write_tokens": self.cache_write_tokens}


def price_table(model: str) -> dict[str, float] | None:
    if model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    for key, table in PRICES_PER_MTOK.items():  # tolerate a dated suffix
        if model.startswith(key):
            return table
    return None


def cost_usd(model: str, usage: Usage) -> float:
    table = price_table(model)
    if table is None:
        from .logging_setup import log_event

        log_event("unknown_model_price", "error", model=model, note="cost recorded as 0: add the model to PRICES_PER_MTOK in app/config.py")
        return 0.0
    total = (usage.input_tokens * table["input"] + usage.output_tokens * table["output"]
             + usage.cache_read_tokens * table["cache_read"] + usage.cache_write_tokens * table["cache_write"])
    return round(total / 1_000_000, 6)
