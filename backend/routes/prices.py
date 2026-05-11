"""GET /api/prices?tickers=NVDA,AVGO — live price snapshot.

Primary: BBG `bdp(PX_LAST, CHG_PCT_1D)` via the LAN server (~150ms for 60 names).
Fallback: Yahoo Finance public chart endpoint (no key needed, batched in groups of 6).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Query

from .. import bbg_adapter, universe

router = APIRouter()

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (PortfolioDashboard/2.0)"}


async def _yahoo_one(client: httpx.AsyncClient, symbol: str) -> tuple[str, dict | None]:
    try:
        r = await client.get(YAHOO_URL.format(symbol=symbol), headers=YAHOO_HEADERS, timeout=8.0)
        r.raise_for_status()
        data = r.json()
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            return symbol, None
        meta = result[0].get("meta") or {}
        px = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if px is None:
            return symbol, None
        chg_pct = ((px - prev) / prev * 100.0) if prev else None
        return symbol, {
            "price": float(px),
            "chg_pct": float(chg_pct) if chg_pct is not None else None,
            "source": "yahoo",
            "currency": meta.get("currency"),
        }
    except Exception:
        return symbol, None


async def _yahoo_batch(symbols: list[str]) -> dict[str, dict]:
    """Fetch many symbols concurrently (small concurrency to stay polite)."""
    out: dict[str, dict] = {}
    sem = asyncio.Semaphore(6)

    async def go(client: httpx.AsyncClient, sym: str):
        async with sem:
            symbol, payload = await _yahoo_one(client, sym)
            if payload is not None:
                out[symbol] = payload

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[go(client, s) for s in symbols])
    return out


def _bbg_batch(bbg_tickers: list[str]) -> dict[str, dict]:
    """Snapshot via the Capstone BBG wrapper. Returns dict keyed by BBG ticker."""
    df = bbg_adapter.bdp(bbg_tickers, ["PX_LAST", "CHG_PCT_1D"])
    out: dict[str, dict] = {}
    if df is None or df.empty:
        return out
    for bbg_t, row in df.iterrows():
        px = row.get("PX_LAST")
        chg = row.get("CHG_PCT_1D")
        if px is None:
            continue
        try:
            out[bbg_t] = {
                "price": float(px),
                "chg_pct": float(chg) if chg is not None else None,
                "source": "bbg",
            }
        except (TypeError, ValueError):
            continue
    return out


@router.get("/prices")
async def get_prices(tickers: str = Query(..., description="Comma-separated ticker list")) -> dict[str, Any]:
    requested = [t.strip() for t in tickers.split(",") if t.strip()]
    by_ticker: dict[str, dict] = {}
    source_used = "none"
    error: str | None = None

    # 1) Try BBG (best for global tickers like "ENR GY")
    if bbg_adapter.is_available():
        try:
            bbg_map = {universe.get(t)["bbg_ticker"] if universe.get(t) else f"{t} US Equity": t for t in requested}
            bbg_result = _bbg_batch(list(bbg_map.keys()))
            for bbg_t, payload in bbg_result.items():
                local_t = bbg_map.get(bbg_t)
                if local_t:
                    by_ticker[local_t] = payload
            if by_ticker:
                source_used = "bbg"
        except Exception as exc:
            error = f"bbg failed: {exc}"

    # 2) Fill gaps from Yahoo (or use Yahoo entirely if BBG returned nothing)
    missing = [t for t in requested if t not in by_ticker]
    if missing:
        # Strip BBG-specific tickers that Yahoo wouldn't understand (e.g. "ENR GY")
        yahoo_lookup = {}
        for t in missing:
            sym = t.split(" ")[0].split(".")[0] if " " in t else t
            yahoo_lookup[sym] = t
        yahoo_result = await _yahoo_batch(list(yahoo_lookup.keys()))
        for sym, payload in yahoo_result.items():
            local_t = yahoo_lookup.get(sym)
            if local_t:
                by_ticker[local_t] = payload
        if source_used == "none" and by_ticker:
            source_used = "yahoo"
        elif source_used == "bbg" and yahoo_result:
            source_used = "mixed"

    return {
        "prices": by_ticker,
        "source": source_used,
        "requested": len(requested),
        "returned": len(by_ticker),
        "error": error,
    }
