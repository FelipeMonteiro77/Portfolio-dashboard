"""GET /api/emails?ticker=NVDA — search recent Outlook emails for a ticker.

Strategy: maintain an on-disk cache of the last N days of emails (refreshed
on demand by shelling out to the existing C:/Users/felipe.monteiro/scripts/outlook.py),
then filter the cache by the ticker's alias list in-memory.

This avoids re-scanning MAPI on every click (which is slow) and reuses the
battle-tested fetch logic from the morning-briefing skill.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import universe

router = APIRouter()

OUTLOOK_SCRIPT = Path(r"C:/Users/felipe.monteiro/scripts/outlook.py")
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "backend" / "data" / "emails_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = 15 * 60  # refresh in-memory cache every 15 min
DEFAULT_DAYS = 7

_refresh_lock = asyncio.Lock()


def _cache_age() -> float:
    if not CACHE_PATH.exists():
        return float("inf")
    return time.time() - CACHE_PATH.stat().st_mtime


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {"metadata": {"fetched_at": None}, "emails": []}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"metadata": {"fetched_at": None}, "emails": []}


async def _refresh_cache(days: int = DEFAULT_DAYS) -> dict:
    """Spawn outlook.py to repopulate the cache. Held by lock so only one refresh at a time."""
    async with _refresh_lock:
        # Re-check inside lock: another caller might have just refreshed.
        if _cache_age() < CACHE_TTL_SECONDS:
            return _load_cache()
        cmd = [
            sys.executable,
            str(OUTLOOK_SCRIPT),
            "--days", str(days),
            "--no-body",                     # body fetch is expensive; we only need metadata for filtering
            "-o", str(CACHE_PATH),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"outlook.py failed (code {proc.returncode}): {stderr.decode('utf-8', 'replace')[:500]}"
            )
        return _load_cache()


def _match(email: dict, aliases: list[str]) -> bool:
    haystack = ((email.get("subject") or "") + " " + (email.get("body_preview") or "")).lower()
    return any(a.lower() in haystack for a in aliases if a)


@router.get("/emails")
async def get_emails(
    ticker: str = Query(...),
    days: int = Query(DEFAULT_DAYS, ge=1, le=30),
    limit: int = Query(30, ge=1, le=200),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    entry = universe.get(ticker)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"ticker {ticker} not in universe")
    aliases = universe.email_aliases(ticker)

    if refresh or _cache_age() > CACHE_TTL_SECONDS:
        try:
            await _refresh_cache(days=days)
        except Exception as exc:
            if not CACHE_PATH.exists():
                raise HTTPException(status_code=503, detail=str(exc))
            # otherwise fall through and serve stale

    cache = _load_cache()
    emails = cache.get("emails") or []
    hits = [e for e in emails if _match(e, aliases)]
    hits.sort(key=lambda e: e.get("date") or "", reverse=True)
    hits = hits[:limit]

    return {
        "ticker": ticker,
        "aliases": aliases,
        "cache_age_seconds": int(_cache_age()) if CACHE_PATH.exists() else None,
        "cache_fetched_at": (cache.get("metadata") or {}).get("fetched_at"),
        "count": len(hits),
        "emails": hits,
    }


@router.post("/emails/refresh")
async def refresh_emails(days: int = Query(DEFAULT_DAYS, ge=1, le=30)) -> dict[str, Any]:
    try:
        cache = await _refresh_cache(days=days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "ok": True,
        "fetched_at": (cache.get("metadata") or {}).get("fetched_at"),
        "emails": len(cache.get("emails") or []),
    }
