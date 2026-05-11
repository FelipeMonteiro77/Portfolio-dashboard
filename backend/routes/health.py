"""GET /api/health — frontend probes this to decide rich vs degraded mode."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter

from .. import bbg_adapter, universe

router = APIRouter()

TWEET_DB = Path(r"C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite")


def _tweet_db_status() -> dict:
    if not TWEET_DB.exists():
        return {"available": False, "rows": 0, "reason": "db not found"}
    try:
        con = sqlite3.connect(f"file:{TWEET_DB}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        finally:
            con.close()
        return {"available": True, "rows": rows}
    except Exception as exc:
        return {"available": False, "rows": 0, "reason": str(exc)}


def _outlook_status() -> dict:
    # win32com is the path the outlook.py CLI uses. We don't open Outlook here
    # (that's expensive) — just check the module imports and the script exists.
    script = Path(r"C:/Users/felipe.monteiro/scripts/outlook.py")
    try:
        import win32com.client  # noqa: F401
        win32_ok = True
    except Exception:
        win32_ok = False
    return {"available": win32_ok and script.exists(), "script_present": script.exists(), "win32com": win32_ok}


@router.get("/health")
def health():
    return {
        "ok": True,
        "bbg": {"available": bbg_adapter.is_available(), "error": bbg_adapter.import_error()},
        "tweets": _tweet_db_status(),
        "outlook": _outlook_status(),
        "universe": {"count": len(universe.get_entries())},
        "pid": os.getpid(),
    }
