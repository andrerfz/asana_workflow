"""Track real Anthropic *API* usage (the paid ANTHROPIC_API_KEY, used only by
AI classification) by reading the `usage` block returned on each response.

This is real Anthropic data — the token counts come straight from the API — but
priced client-side from the model. It is NOT the account's remaining credit:
the Messages API does not expose a balance endpoint (only the Admin API reports
org-level spend, and that needs an admin key). So we report *spend*, per day.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from ..config import DATA_DIR

log = logging.getLogger(__name__)

_USAGE_FILE = Path(DATA_DIR) / "api_usage.json"
_lock = Lock()

# USD per token, by model family. Source: Anthropic pricing (per 1M tokens).
_PRICING = {
    "haiku":  {"in": 1.0 / 1_000_000,  "out": 5.0 / 1_000_000},
    "sonnet": {"in": 3.0 / 1_000_000,  "out": 15.0 / 1_000_000},
    "opus":   {"in": 5.0 / 1_000_000,  "out": 25.0 / 1_000_000},
    "fable":  {"in": 10.0 / 1_000_000, "out": 50.0 / 1_000_000},
}


def _price_for(model: str) -> dict:
    m = (model or "").lower()
    for family, price in _PRICING.items():
        if family in m:
            return price
    return _PRICING["sonnet"]  # safe mid-tier default


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    if _USAGE_FILE.exists():
        try:
            return json.loads(_USAGE_FILE.read_text())
        except Exception:
            return {}
    return {}


def record_api_usage(model: str, usage: dict) -> None:
    """Accumulate one API call's usage into today's bucket. `usage` is the
    Anthropic response `usage` object (input_tokens, output_tokens, and the
    optional cache_* fields)."""
    if not isinstance(usage, dict):
        return
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0

    price = _price_for(model)
    cost = (
        inp * price["in"]
        + out * price["out"]
        + cache_write * price["in"] * 1.25
        + cache_read * price["in"] * 0.1
    )

    with _lock:
        data = _load()
        day = data.setdefault(_today(), {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0})
        day["cost_usd"] += cost
        day["input_tokens"] += inp + cache_write + cache_read
        day["output_tokens"] += out
        day["calls"] += 1
        try:
            _USAGE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.warning("Failed to persist API usage: %s", e)


def today_usage() -> dict:
    """Return today's classification spend snapshot."""
    day = _load().get(_today(), {})
    return {
        "cost_usd": round(day.get("cost_usd", 0.0), 4),
        "input_tokens": day.get("input_tokens", 0),
        "output_tokens": day.get("output_tokens", 0),
        "calls": day.get("calls", 0),
    }
