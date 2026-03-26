"""
Token usage and cost tracker.

Stores every LLM call in SQLite — provider, model, tokens, cost, latency.
Provides query helpers for the /api/usage endpoint.
"""

from __future__ import annotations

import sqlite3
import time
import os
from dataclasses import dataclass
from datetime import datetime, timezone

# Price per 1M tokens (input, output) in USD.
# Ollama is free (local). Update as pricing changes.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI — GPT-5 family
    "gpt-5.4":           (2.50,  15.00),
    "gpt-5.4-mini":      (0.75,   4.50),
    "gpt-5.4-nano":      (0.20,   1.25),
    "gpt-5.4-pro":       (30.00, 180.00),
    "gpt-5.2":           (1.75,  14.00),
    "gpt-5.2-pro":       (30.00, 180.00),
    "gpt-5":             (1.75,  14.00),
    "gpt-5-mini":        (0.75,   4.50),
    "gpt-5-nano":        (0.05,   0.40),
    "gpt-5-pro":         (30.00, 180.00),
    # OpenAI — GPT-4 family
    "gpt-4o":            (2.50,  10.00),
    "gpt-4o-mini":       (0.15,   0.60),
    "gpt-4-turbo":       (10.00, 30.00),
    # OpenAI — o-series reasoning
    "o1":                (15.00, 60.00),
    "o1-mini":           (1.10,   4.40),
    "o3-mini":           (1.10,   4.40),
    # Gemini 3.x
    "gemini-3.1-pro-preview":        (2.00, 12.00),
    "gemini-3.1-flash-lite-preview": (0.25,  1.50),
    "gemini-3-flash-preview":        (0.50,  3.00),
    # Gemini 2.5
    "gemini-2.5-pro":        (1.25, 10.00),
    "gemini-2.5-flash":      (0.30,  2.50),
    "gemini-2.5-flash-lite": (0.10,  0.40),
    # Gemini 2.0 / 1.5
    "gemini-2.0-flash":  (0.10,  0.40),
    "gemini-1.5-pro":    (1.25,  5.00),
    "gemini-1.5-flash":  (0.075, 0.30),
    # Anthropic
    "claude-sonnet-4-20250514":    (3.00, 15.00),
    "claude-haiku-3-20250414":     (0.80,  4.00),
    "claude-3-5-sonnet-20241022":  (3.00, 15.00),
    "claude-3-5-haiku-20241022":   (0.80,  4.00),
    "claude-3-opus-20240229":      (15.00, 75.00),
    # Groq
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant":    (0.05, 0.08),
    "mixtral-8x7b-32768":      (0.24, 0.24),
}

DB_PATH = os.environ.get("USAGE_DB", "usage.db")

_db_initialized = False


def _get_conn() -> sqlite3.Connection:
    global _db_initialized
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if not _db_initialized:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                provider    TEXT    NOT NULL,
                model       TEXT    NOT NULL,
                tokens_in   INTEGER NOT NULL DEFAULT 0,
                tokens_out  INTEGER NOT NULL DEFAULT 0,
                cost_usd    REAL    NOT NULL DEFAULT 0,
                latency_ms  INTEGER NOT NULL DEFAULT 0,
                method      TEXT    NOT NULL DEFAULT 'generate'
            )
        """)
        conn.commit()
        _db_initialized = True
    return conn


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    price_in, price_out = pricing
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


@dataclass
class UsageEvent:
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    method: str = "generate"


def log_usage(event: UsageEvent):
    """Write a usage event to the DB (sync — called from a background thread if needed)."""
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO usage (timestamp, provider, model, tokens_in, tokens_out, cost_usd, latency_ms, method) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                event.provider,
                event.model,
                event.tokens_in,
                event.tokens_out,
                event.cost_usd,
                event.latency_ms,
                event.method,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_usage_summary() -> dict:
    """Aggregate usage stats for the API endpoint."""
    conn = _get_conn()

    total = conn.execute(
        "SELECT COUNT(*) as calls, "
        "COALESCE(SUM(tokens_in), 0) as tokens_in, "
        "COALESCE(SUM(tokens_out), 0) as tokens_out, "
        "COALESCE(SUM(cost_usd), 0) as cost_usd "
        "FROM usage"
    ).fetchone()

    by_model = conn.execute(
        "SELECT model, provider, COUNT(*) as calls, "
        "SUM(tokens_in) as tokens_in, SUM(tokens_out) as tokens_out, "
        "ROUND(SUM(cost_usd), 6) as cost_usd, "
        "ROUND(AVG(latency_ms), 0) as avg_latency_ms "
        "FROM usage GROUP BY model ORDER BY cost_usd DESC"
    ).fetchall()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_row = conn.execute(
        "SELECT COUNT(*) as calls, "
        "COALESCE(SUM(tokens_in), 0) as tokens_in, "
        "COALESCE(SUM(tokens_out), 0) as tokens_out, "
        "COALESCE(SUM(cost_usd), 0) as cost_usd "
        "FROM usage WHERE timestamp LIKE ?",
        (f"{today}%",),
    ).fetchone()

    recent = conn.execute(
        "SELECT timestamp, provider, model, tokens_in, tokens_out, "
        "ROUND(cost_usd, 6) as cost_usd, latency_ms, method "
        "FROM usage ORDER BY id DESC LIMIT 20"
    ).fetchall()

    conn.close()

    return {
        "total": {
            "calls": total["calls"],
            "tokens_in": total["tokens_in"],
            "tokens_out": total["tokens_out"],
            "cost_usd": round(total["cost_usd"], 6),
        },
        "today": {
            "calls": today_row["calls"],
            "tokens_in": today_row["tokens_in"],
            "tokens_out": today_row["tokens_out"],
            "cost_usd": round(today_row["cost_usd"], 6),
        },
        "by_model": [dict(row) for row in by_model],
        "recent": [dict(row) for row in recent],
    }
