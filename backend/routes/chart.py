"""GET /api/chart?ticker=NVDA&range=1mo&interval=1d — historical OHLC for the drawer."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from .. import universe

router = APIRouter()
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
HEADERS = {"User-Agent": "Mozilla/5.0 (PortfolioDashboard/2.0)"}

ALLOWED_RANGES = {"5d", "1mo", "3mo", "6mo", "1y", "5y"}
ALLOWED_INTERVALS = {"5m", "15m", "30m", "1h", "1d", "1wk"}


@router.get("/chart")
async def get_chart(
    ticker: str = Query(...),
    range_: str = Query("1mo", alias="range"),
    interval: str = Query("1d"),
):
    if range_ not in ALLOWED_RANGES or interval not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail="invalid range/interval")
    sym = ticker
    if universe.get(ticker):
        # If the ticker contains a space (e.g. "ENR GY"), Yahoo doesn't know it; trim.
        sym = ticker.split(" ")[0]
    url = YAHOO_URL.format(symbol=sym, interval=interval, range_=range_)
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"yahoo {r.status_code}")
        data = r.json()
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return {"ticker": ticker, "timestamps": [], "close": [], "open": [], "high": [], "low": [], "volume": []}
    r0 = result[0]
    quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    return {
        "ticker": ticker,
        "timestamps": r0.get("timestamp") or [],
        "close": quote.get("close") or [],
        "open": quote.get("open") or [],
        "high": quote.get("high") or [],
        "low": quote.get("low") or [],
        "volume": quote.get("volume") or [],
        "currency": (r0.get("meta") or {}).get("currency"),
    }
