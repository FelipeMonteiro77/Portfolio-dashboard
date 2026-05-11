"""GET /api/news/feed — unified news tab.

Returns:
    - Tweets from the local SQLite corpus (last N hours, ex-RT, ex-reply),
      tagged with all universe tickers they mention.
    - Emails from the cached Outlook fetch (already populated by /api/emails),
      tagged with all universe tickers they mention.

No external API calls. All data is local: SQLite + the on-disk emails_cache.json.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from .. import universe

router = APIRouter()

TWEETS_DB = Path(r"C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite")
EMAILS_CACHE = Path(__file__).resolve().parent.parent / "data" / "emails_cache.json"


def _fetch_tweets(hours: int, limit: int) -> list[dict]:
    if not TWEETS_DB.exists():
        return []
    con = sqlite3.connect(f"file:{TWEETS_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT tweet_id, handle, author_name, category, created_at, text, url,
                   is_quote, like_count, retweet_count, reply_count, view_count
            FROM tweets
            WHERE created_at >= datetime('now', ?)
              AND is_retweet = 0
              AND is_reply = 0
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (f"-{hours} hours", limit * 4),  # over-fetch — we'll filter by universe
        ).fetchall()
    finally:
        con.close()

    out: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        hits = universe.match_text(text, kind="tweet")
        if not hits:
            continue
        out.append({
            "kind": "tweet",
            "id": r["tweet_id"],
            "ts": r["created_at"],
            "handle": r["handle"],
            "author": r["author_name"],
            "category": r["category"],
            "text": text,
            "url": r["url"],
            "is_quote": bool(r["is_quote"]),
            "likes": r["like_count"] or 0,
            "retweets": r["retweet_count"] or 0,
            "replies": r["reply_count"] or 0,
            "views": r["view_count"] or 0,
            "tickers": hits,
        })
        if len(out) >= limit:
            break
    return out


def _fetch_emails(limit: int) -> list[dict]:
    if not EMAILS_CACHE.exists():
        return []
    try:
        with open(EMAILS_CACHE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    emails = data.get("emails") or []
    out: list[dict] = []
    for e in emails:
        haystack = (e.get("subject") or "") + " " + (e.get("body_preview") or "")
        hits = universe.match_text(haystack, kind="email")
        if not hits:
            continue
        out.append({
            "kind": "email",
            "id": e.get("entry_id") or "",
            "ts": e.get("date") or "",
            "sender": e.get("sender") or "",
            "sender_email": e.get("sender_email") or "",
            "subject": e.get("subject") or "",
            "preview": e.get("body_preview") or "",
            "folder": e.get("folder") or "",
            "tickers": hits,
        })
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out


@router.get("/news/feed")
def get_news_feed(
    hours: int = Query(48, ge=1, le=240, description="Tweet lookback window in hours"),
    tweet_limit: int = Query(100, ge=1, le=400),
    email_limit: int = Query(100, ge=1, le=400),
    ticker: str | None = Query(None, description="Restrict to a single ticker"),
    sector: str | None = Query(None, description="Restrict to tickers in a sector (substring match)"),
) -> dict[str, Any]:
    tweets = _fetch_tweets(hours=hours, limit=tweet_limit)
    emails = _fetch_emails(limit=email_limit)

    if ticker:
        tweets = [t for t in tweets if ticker in t["tickers"]]
        emails = [e for e in emails if ticker in e["tickers"]]
    elif sector:
        sl = sector.lower()
        allowed = {
            u["ticker"] for u in universe.get_entries()
            if sl in (u.get("sector") or "").lower()
        }
        tweets = [t for t in tweets if set(t["tickers"]) & allowed]
        emails = [e for e in emails if set(e["tickers"]) & allowed]

    # Ticker frequency tally for the filter chips
    counts: dict[str, int] = {}
    for it in tweets + emails:
        for t in it["tickers"]:
            counts[t] = counts.get(t, 0) + 1

    sectors = sorted({(u.get("sector") or "Other") for u in universe.get_entries()})

    return {
        "tweets": tweets,
        "emails": emails,
        "tweet_count": len(tweets),
        "email_count": len(emails),
        "emails_cache_present": EMAILS_CACHE.exists(),
        "ticker_counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "sectors": sectors,
    }
