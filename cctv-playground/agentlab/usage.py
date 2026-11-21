"""Token and cost log for every model call: one JSON line per call in runs/usage.jsonl.

Every script that calls Gemini or Claude should end each call with log_call(...), so the
cost KPI and our own spend come from the same file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE_LOG = ROOT / "runs" / "usage.jsonl"

# USD per million tokens. Source: project doc "Agents and tools exploration",
# list prices checked 20 Nov 2026; gemini-4-hydrogen from Google's 12 Nov 2026 launch
# pricing (AI Studio shows the same). Re-check before quoting them in the business case.
# gemini-3.8-flash doubles to $1.50 / $7.50 from 1 Jan 2027 (see PRICES_2027).
PRICES: dict[str, dict] = {
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-4-hydrogen": {"input": 1.50, "output": 7.50},
    # Haiku 5.5 is priced by prompt length; the higher rate applies above 100K input tokens.
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50,
                         "long": {"above": 100_000, "input": 0.50, "output": 2.50}},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
}


# Prices a customer would pay from 2027 (the business case should use these).
PRICES_2027: dict[str, dict] = {**PRICES, "gemini-3.8-flash": {"input": 1.50, "output": 7.50}}


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             prices: dict[str, dict] | None = None) -> float | None:
    """Cost of one call. output_tokens must include thinking tokens (both providers bill them as output)."""
    price = (prices or PRICES).get(model)
    if price is None:
        return None
    long = price.get("long")
    if long and input_tokens > long["above"]:
        price = long
    return round((input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000, 6)


def log_call(*, provider: str, model: str, input_tokens: int, output_tokens: int,
             seconds: float, tag: str = "", thinking_tokens: int = 0, extra: dict | None = None) -> dict:
    """Append one call to runs/usage.jsonl and return the row (with cost_usd)."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tag": tag,
        "provider": provider,
        "model": model,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "thinking_tokens": int(thinking_tokens or 0),
        "seconds": round(seconds, 2),
        "cost_usd": cost_usd(model, int(input_tokens or 0), int(output_tokens or 0)),
    }
    if extra:
        row.update(extra)
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def total_spend(provider: str | None = None) -> float:
    """Sum of logged cost so far (all runs), optionally for one provider."""
    if not USAGE_LOG.exists():
        return 0.0
    total = 0.0
    for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if provider and row.get("provider") != provider:
            continue
        total += row.get("cost_usd") or 0.0
    return round(total, 6)
