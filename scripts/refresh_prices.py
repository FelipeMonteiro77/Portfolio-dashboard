"""Lightweight Yahoo-only price snapshot → data/prices.json.

Designed for GitHub Actions (no BBG access). Mirrors the structure of the
existing .github/workflows/update-prices.py but reads tickers from
config/tickers.yaml instead of hard-coded constants. Frontend reads this
file as a fallback when /api/prices is unreachable.

Run:
    python scripts/refresh_prices.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "prices.json"
CONFIG_PATH = ROOT / "config" / "tickers.yaml"

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
HEADERS = {"User-Agent": "Mozilla/5.0 (PortfolioDashboard/2.0 +github-actions)"}


def fetch_one(session: requests.Session, ticker: str) -> dict | None:
    sym = ticker.split(" ")[0]  # BBG tickers like "ENR GY" -> "ENR" (will likely miss; we skip those)
    try:
        r = session.get(URL.format(symbol=sym), headers=HEADERS, timeout=8.0)
        r.raise_for_status()
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        px = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if px is None:
            return None
        chg_pct = ((px - prev) / prev * 100.0) if prev else None
        return {"price": float(px), "chg_pct": chg_pct, "currency": meta.get("currency")}
    except Exception:
        return None


def main() -> int:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get("universe") or []
    tickers = [e["ticker"] for e in entries if not e.get("pseudo")]

    session = requests.Session()
    out: dict[str, dict] = {}
    for t in tickers:
        info = fetch_one(session, t)
        if info:
            out[t] = info
        time.sleep(0.05)  # polite pacing

    payload = {
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "yahoo",
        "count": len(out),
        "prices": out,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} prices to {OUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
