"""GET/POST /api/tickers — read & extend the universe at runtime."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import universe

router = APIRouter()


class AliasBlock(BaseModel):
    email: list[str] = Field(default_factory=list)
    tweet: list[str] = Field(default_factory=list)


class TickerIn(BaseModel):
    ticker: str
    bbg_ticker: str | None = None
    name: str | None = None
    sector: str | None = None
    in_valuation: bool = False
    tweet_cashtag_only: bool = False
    pseudo: bool = False
    capstone_eps: dict[str, float] | None = None
    px_seed: float | None = None
    search_aliases: AliasBlock = Field(default_factory=AliasBlock)


@router.get("/tickers")
def list_tickers() -> dict[str, Any]:
    entries = universe.get_entries()
    return {"count": len(entries), "universe": entries}


@router.post("/tickers")
def add_ticker(payload: TickerIn) -> dict[str, Any]:
    if universe.get(payload.ticker):
        raise HTTPException(status_code=409, detail=f"ticker {payload.ticker} already exists")
    entry = payload.model_dump(exclude_none=True)
    entry["search_aliases"] = {
        "email": list(payload.search_aliases.email),
        "tweet": list(payload.search_aliases.tweet),
    }
    try:
        added = universe.append(entry)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "added": added}


@router.post("/tickers/reload")
def reload_universe() -> dict[str, Any]:
    """Re-read tickers.yaml from disk (useful after editing the file directly)."""
    universe.load()
    return {"ok": True, "count": len(universe.get_entries())}
