"""GET /api/tweets?ticker=NVDA — local SQLite FTS5 query against the daily corpus."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import universe

router = APIRouter()
DB_PATH = Path(r"C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite")


def _build_fts_query(aliases: list[str]) -> str:
    """Build an FTS5 MATCH expression from a list of alias strings.

    Multi-word aliases get quoted as phrases; single tokens are OR'd."""
    parts: list[str] = []
    for a in aliases:
        a = a.strip()
        if not a:
            continue
        # FTS5 doesn't index "$" — strip the cashtag prefix; we'll boost with a substring filter
        cleaned = a.lstrip("$").strip()
        if not cleaned:
            continue
        if " " in cleaned or "-" in cleaned:
            parts.append(f'"{cleaned}"')
        else:
            parts.append(cleaned)
    return " OR ".join(dict.fromkeys(parts)) if parts else ""


@router.get("/tweets")
def get_tweets(
    ticker: str = Query(...),
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
    include_retweets: bool = Query(False),
) -> dict[str, Any]:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"tweets db not found at {DB_PATH}")

    entry = universe.get(ticker)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"ticker {ticker} not in universe")

    aliases = universe.tweet_aliases(ticker)
    match = _build_fts_query(aliases)
    if not match:
        return {"ticker": ticker, "aliases": aliases, "tweets": [], "count": 0}

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rt_filter = "" if include_retweets else "AND is_retweet = 0 AND is_reply = 0"
        sql = f"""
            SELECT tweet_id, handle, author_name, category, created_at, text, url,
                   is_quote, like_count, retweet_count, reply_count, view_count
            FROM tweets
            WHERE rowid IN (SELECT rowid FROM tweets_fts WHERE tweets_fts MATCH ?)
              AND created_at >= datetime('now', ?)
              {rt_filter}
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """
        rows = con.execute(sql, (match, f"-{hours} hours", limit)).fetchall()
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=500, detail=f"sqlite error: {exc} (match='{match}')")
    finally:
        con.close()

    cashtag_only = bool(entry.get("tweet_cashtag_only"))
    out: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        if cashtag_only and f"${ticker}" not in text.upper():
            # FTS dropped the $ — re-check we actually matched the cashtag
            continue
        out.append({
            "id": r["tweet_id"],
            "handle": r["handle"],
            "author": r["author_name"],
            "category": r["category"],
            "ts": r["created_at"],
            "text": text,
            "url": r["url"],
            "is_quote": bool(r["is_quote"]),
            "likes": r["like_count"] or 0,
            "retweets": r["retweet_count"] or 0,
            "replies": r["reply_count"] or 0,
            "views": r["view_count"] or 0,
        })

    return {"ticker": ticker, "aliases": aliases, "match": match, "count": len(out), "tweets": out}
