"""GET /api/repo/* — browse the local Twitter corpus + cached Outlook emails.

Replaces the older /api/news/feed (which only returned items mentioning a
universe ticker). This is a generic repository view over everything we've
already pulled — full-text search, filters, pagination. No external calls.

Endpoints:
    GET /api/repo/meta           → counts, categories, top handles/senders
    GET /api/repo/tweets         → paginated tweet browse (FTS5 + filters)
    GET /api/repo/emails         → paginated email browse (filters)
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from .. import universe

router = APIRouter()

TWEETS_DB = Path(r"C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite")
EMAILS_CACHE = Path(__file__).resolve().parent.parent / "data" / "emails_cache.json"


# ── Helpers ──────────────────────────────────────────────────────────────
def _con():
    return sqlite3.connect(f"file:{TWEETS_DB}?mode=ro", uri=True)


def _fts_query(q: str) -> str:
    """Build an FTS5 MATCH expression from a user-typed string.

    Plain words become AND'd terms; quoted phrases stay as phrases. Empty
    strings → ''. Tokens shorter than 3 chars are dropped (FTS5 chokes on `$`
    and 1-2 char noise)."""
    q = (q or "").strip()
    if not q:
        return ""
    # Phrases in quotes
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]+"', " ", q)
    tokens = [w for w in re.findall(r"\w[\w'-]+", rest) if len(w) >= 3]
    out: list[str] = []
    for p in phrases:
        if p.strip():
            out.append(f'"{p.strip()}"')
    for t in tokens:
        out.append(t)
    return " AND ".join(out)


def _load_email_cache() -> list[dict]:
    if not EMAILS_CACHE.exists():
        return []
    try:
        with open(EMAILS_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("emails") or []
    except Exception:
        return []


# ── /api/repo/meta ───────────────────────────────────────────────────────
@router.get("/repo/meta")
def repo_meta() -> dict[str, Any]:
    out: dict[str, Any] = {"tweets": None, "emails": None}

    # Tweet metadata
    if TWEETS_DB.exists():
        with _con() as con:
            total = con.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
            last_24h = con.execute("SELECT COUNT(*) FROM tweets WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
            last_7d = con.execute("SELECT COUNT(*) FROM tweets WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
            cats = dict(con.execute(
                "SELECT category, COUNT(*) c FROM tweets WHERE created_at >= datetime('now','-7 days') GROUP BY category ORDER BY c DESC"
            ).fetchall())
            top_handles = [
                {"handle": h, "n": n}
                for h, n in con.execute(
                    "SELECT handle, COUNT(*) c FROM tweets WHERE created_at >= datetime('now','-7 days') GROUP BY handle ORDER BY c DESC LIMIT 80"
                ).fetchall()
            ]
            date_range = con.execute("SELECT MIN(created_at), MAX(created_at) FROM tweets").fetchone()
        out["tweets"] = {
            "total": total,
            "last_24h": last_24h,
            "last_7d": last_7d,
            "categories": cats,
            "top_handles": top_handles,
            "date_range": date_range,
        }

    # Email metadata
    emails = _load_email_cache()
    if emails:
        sender_counts: dict[str, int] = {}
        folder_counts: dict[str, int] = {}
        for e in emails:
            s = (e.get("sender") or e.get("sender_email") or "?").strip()
            f = (e.get("folder") or "?").strip()
            sender_counts[s] = sender_counts.get(s, 0) + 1
            folder_counts[f] = folder_counts.get(f, 0) + 1
        top_senders = sorted(sender_counts.items(), key=lambda kv: -kv[1])[:80]
        out["emails"] = {
            "total": len(emails),
            "folders": dict(sorted(folder_counts.items(), key=lambda kv: -kv[1])),
            "top_senders": [{"sender": s, "n": n} for s, n in top_senders],
        }
    else:
        out["emails"] = {"total": 0, "folders": {}, "top_senders": []}

    return out


# ── /api/repo/tweets ─────────────────────────────────────────────────────
@router.get("/repo/tweets")
def repo_tweets(
    q: str = Query("", description="Free-text search (FTS5)"),
    hours: int = Query(72, ge=1, le=24 * 365, description="Lookback window"),
    category: str | None = Query(None),
    handle: str | None = Query(None),
    include_retweets: bool = Query(False),
    include_replies: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    if not TWEETS_DB.exists():
        return {"count": 0, "total": 0, "tweets": [], "error": "tweets db missing"}

    where = ["created_at >= datetime('now', ?)"]
    params: list[Any] = [f"-{hours} hours"]
    if not include_retweets:
        where.append("is_retweet = 0")
    if not include_replies:
        where.append("is_reply = 0")
    if category:
        where.append("category = ?")
        params.append(category)
    if handle:
        where.append("LOWER(handle) = ?")
        params.append(handle.lower())

    match = _fts_query(q)
    if match:
        where.append("rowid IN (SELECT rowid FROM tweets_fts WHERE tweets_fts MATCH ?)")
        params.append(match)

    where_sql = " AND ".join(where)
    sql_count = f"SELECT COUNT(*) FROM tweets WHERE {where_sql}"
    sql_rows = f"""
        SELECT tweet_id, handle, author_name, category, created_at, text, url,
               is_quote, like_count, retweet_count, reply_count, view_count
        FROM tweets WHERE {where_sql}
        ORDER BY datetime(created_at) DESC
        LIMIT ? OFFSET ?
    """

    with _con() as con:
        con.row_factory = sqlite3.Row
        try:
            total = con.execute(sql_count, params).fetchone()[0]
            rows = con.execute(sql_rows, [*params, limit, offset]).fetchall()
        except sqlite3.OperationalError as exc:
            return {"count": 0, "total": 0, "tweets": [], "error": f"sqlite: {exc} (match={match!r})"}

    tweets = []
    for r in rows:
        text = r["text"] or ""
        tickers = universe.match_text(text, kind="tweet")
        tweets.append({
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
            "tickers": tickers,
        })

    return {
        "count": len(tweets),
        "total": total,
        "offset": offset,
        "limit": limit,
        "match": match,
        "tweets": tweets,
    }


# ── /api/repo/emails ─────────────────────────────────────────────────────
@router.get("/repo/emails")
def repo_emails(
    q: str = Query(""),
    days: int = Query(7, ge=1, le=60),
    sender: str | None = Query(None),
    folder: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    emails = _load_email_cache()
    if not emails:
        return {"count": 0, "total": 0, "emails": [], "cache_present": False}

    # Filter
    q_lower = (q or "").lower().strip()
    s_lower = (sender or "").lower().strip()
    f_lower = (folder or "").lower().strip()
    out: list[dict] = []
    for e in emails:
        # Date filter is informational only — the cache is already date-scoped
        # at fetch time by outlook.py --days N.
        if s_lower:
            sender_str = ((e.get("sender") or "") + " " + (e.get("sender_email") or "")).lower()
            if s_lower not in sender_str:
                continue
        if f_lower and f_lower not in (e.get("folder") or "").lower():
            continue
        if q_lower:
            haystack = ((e.get("subject") or "") + " " + (e.get("body_preview") or "") + " " + (e.get("body") or "")).lower()
            if q_lower not in haystack:
                continue
        out.append({
            "id": e.get("entry_id") or "",
            "ts": e.get("date") or "",
            "sender": e.get("sender") or "",
            "sender_email": e.get("sender_email") or "",
            "subject": e.get("subject") or "",
            "preview": e.get("body_preview") or "",
            "folder": e.get("folder") or "",
            "tickers": universe.match_text(
                (e.get("subject") or "") + " " + (e.get("body_preview") or ""),
                kind="email",
            ),
        })

    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    total = len(out)
    paged = out[offset: offset + limit]
    return {
        "count": len(paged),
        "total": total,
        "offset": offset,
        "limit": limit,
        "cache_present": True,
        "emails": paged,
    }
