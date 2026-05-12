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

CACHE_TTL_SECONDS = 60 * 60  # 1h — full-body scans are slow (~30s+ for 7 days)
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


def _truncate_bodies(path: Path, max_chars: int) -> None:
    """Trim each email's body to the first `max_chars` characters in-place.

    The Outlook fetch can produce 20KB+ bodies for HTML-heavy research notes.
    Substring matching only needs the first few KB. This keeps the cache file
    under ~5MB even for 7-day fetches with hundreds of emails.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for e in data.get("emails", []):
            body = e.get("body") or ""
            if len(body) > max_chars:
                e["body"] = body[:max_chars]
                changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass  # leave the cache untouched on any failure


async def _refresh_cache(days: int = DEFAULT_DAYS) -> dict:
    """Spawn outlook.py to repopulate the cache. Held by lock so only one refresh at a time."""
    async with _refresh_lock:
        # Re-check inside lock: another caller might have just refreshed.
        if _cache_age() < CACHE_TTL_SECONDS:
            return _load_cache()
        # Pull full bodies — when someone clicks a ticker we want substring
        # matches against the body too (e.g. spec-sales remarks where the
        # ticker is buried in paragraph 4, not the subject line).
        cmd = [
            sys.executable,
            str(OUTLOOK_SCRIPT),
            "--days", str(days),
            "-o", str(CACHE_PATH),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")[:1000].strip()
            # The most common failure: Outlook desktop is closed → COM call
            # raises "Erro ao conectar ao Outlook" / "Outlook is not running".
            if "outlook" in err_text.lower() or "com" in err_text.lower():
                raise RuntimeError(
                    "Outlook desktop is not running. Open the Outlook app on your "
                    "Windows desktop, wait for the inbox to load, then click "
                    "Refresh again."
                )
            raise RuntimeError(
                f"outlook.py failed (code {proc.returncode}): {err_text}"
            )
        # Truncate bodies to keep the cache compact (4 KB is plenty for ticker
        # matching; research notes rarely have important content past the first
        # screen).
        _truncate_bodies(CACHE_PATH, max_chars=4000)
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
