"""Track Claude (cloud) usage so you can monitor how much you're spending.

Persisted to data/usage.json. Cost is estimated from the per-model rates below
(USD per 1M tokens); update PRICING if Anthropic's pricing changes.
"""

from __future__ import annotations

import json
from datetime import date

from .config import ROOT

_USAGE = ROOT / "data" / "usage.json"

# (input $/1M, output $/1M)
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_DEFAULT_RATE = (5.0, 25.0)


def _empty() -> dict:
    return {"total_input": 0, "total_output": 0, "total_cost": 0.0, "calls": 0,
            "by_model": {}, "by_day": {},
            # Timing (all AI calls, Ollama + Claude):
            "total_seconds": 0.0, "timed_calls": 0,
            "last_seconds": 0.0, "last_model": "", "last_label": ""}


def _load() -> dict:
    if _USAGE.exists():
        try:
            d = json.loads(_USAGE.read_text(encoding="utf-8"))
            for k, v in _empty().items():
                d.setdefault(k, v)
            return d
        except ValueError:
            return _empty()
    return _empty()


def record(model: str, input_tokens: int, output_tokens: int, *, label: str = "") -> float:
    """Add one Claude call's usage; returns the estimated cost in USD."""
    pin, pout = PRICING.get(model, _DEFAULT_RATE)
    cost = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout

    d = _load()
    d["total_input"] += int(input_tokens)
    d["total_output"] += int(output_tokens)
    d["total_cost"] = round(d["total_cost"] + cost, 6)
    d["calls"] += 1

    for bucket_key, bucket in (("by_model", model), ("by_day", str(date.today()))):
        b = d[bucket_key].setdefault(bucket, {"input": 0, "output": 0, "cost": 0.0, "calls": 0})
        b["input"] += int(input_tokens)
        b["output"] += int(output_tokens)
        b["cost"] = round(b["cost"] + cost, 6)
        b["calls"] += 1

    _USAGE.parent.mkdir(parents=True, exist_ok=True)
    _USAGE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return cost


def record_time(model: str, seconds: float, *, label: str = "") -> None:
    """Record how long one AI request took (any engine). Aggregated overall, per
    model, and per day, plus the most recent call's duration."""
    seconds = round(float(seconds), 3)
    d = _load()
    d["total_seconds"] = round(d.get("total_seconds", 0.0) + seconds, 3)
    d["timed_calls"] = d.get("timed_calls", 0) + 1
    d["last_seconds"] = seconds
    d["last_model"] = model
    d["last_label"] = label

    for bucket_key, bucket in (("by_model", model), ("by_day", str(date.today()))):
        b = d[bucket_key].setdefault(bucket, {"input": 0, "output": 0, "cost": 0.0, "calls": 0})
        b["seconds"] = round(b.get("seconds", 0.0) + seconds, 3)
        b["timed_calls"] = b.get("timed_calls", 0) + 1

    _USAGE.parent.mkdir(parents=True, exist_ok=True)
    _USAGE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def summary() -> dict:
    d = _load()
    tc = d.get("timed_calls", 0)
    d["avg_seconds"] = round(d.get("total_seconds", 0.0) / tc, 3) if tc else 0.0
    return d
