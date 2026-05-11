"""GET /api/consensus?ticker=NVDA — live BBG consensus snapshot.

Pulls the same BEST_* fields the Consenso.ipynb workbook uses. Also returns
the broker grid (BEST_EPS_ANALYST_FORECASTS) when available.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import bbg_adapter, universe

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = ROOT / "data" / "consensus.json"

FIELDS = [
    "BEST_EPS",
    "BEST_SALES",
    "BEST_EBITDA",
    "BEST_TARGET_PRICE",
    "BEST_ANALYST_RATING",
    "PE_RATIO",
]


def _load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {"updated_at": None, "tickers": {}}
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "tickers": {}}


@router.get("/consensus/snapshot")
def get_snapshot() -> dict[str, Any]:
    """Return the most recent BBG snapshot committed to disk."""
    return _load_snapshot()


@router.get("/consensus")
def get_consensus(
    ticker: str = Query(...),
    refresh: bool = Query(False, description="Force a fresh BBG pull instead of reading the snapshot"),
) -> dict[str, Any]:
    entry = universe.get(ticker)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"ticker {ticker} not in universe")

    if not refresh:
        snap = _load_snapshot()
        cached = (snap.get("tickers") or {}).get(ticker)
        if cached:
            return {"ticker": ticker, "source": "snapshot", "updated_at": snap.get("updated_at"), **cached}

    if not bbg_adapter.is_available():
        raise HTTPException(status_code=503, detail="BBG unavailable and no snapshot cached for this ticker")

    bbg_t = entry["bbg_ticker"]
    try:
        df = bbg_adapter.bdp([bbg_t], FIELDS)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bdp failed: {exc}")

    if df is None or df.empty:
        raise HTTPException(status_code=502, detail="BBG returned no data")

    row = df.iloc[0]
    payload = {f.lower(): (float(row[f]) if row.get(f) is not None else None) for f in FIELDS if f in df.columns}

    # Broker grid (optional — some tickers don't have one)
    brokers: list[dict] = []
    try:
        grid = bbg_adapter.bds(bbg_t, "BEST_EPS_ANALYST_FORECASTS")
        if grid is not None and not grid.empty:
            for _, r in grid.iterrows():
                brokers.append({k: (None if (v is None or (isinstance(v, float) and v != v)) else v) for k, v in r.to_dict().items()})
    except Exception:
        pass

    out = {
        "ticker": ticker,
        "source": "bbg-live",
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "fields": payload,
        "brokers": brokers,
    }

    # Persist into the snapshot file so a later cache read can serve it.
    try:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        snap = _load_snapshot()
        snap.setdefault("tickers", {})[ticker] = {"fields": payload, "brokers": brokers}
        snap["updated_at"] = out["updated_at"]
        with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return out
