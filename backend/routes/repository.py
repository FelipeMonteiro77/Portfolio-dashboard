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
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from .. import universe

router = APIRouter()

TWEETS_DB = Path(r"C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite")
EMAILS_CACHE = Path(__file__).resolve().parent.parent / "data" / "emails_cache.json"

# Pure-noise handles (re-tweeted newswire feeds). From twitter_match.py.
DROP_HANDLES = {"firstsquawk", "livesquawk", "fxmarketalerts", "fxhedgers"}

# Tier-1 voices we always want to surface even on lower engagement.
# (Mirrors the canonical list in twitter_match.py — kept inline to avoid
# coupling the backend to that skill module.)
TIER1 = {
    h.lower() for h in [
        "dylan522p", "SemiAnalysis_", "Srasgon", "SKundojjala", "sssjeffpu", "mingchikuo",
        "insane_analyst", "austinsemis", "firstadopter", "PatrickMoorhead", "BenBajarin",
        "fabknowledge", "DylanOnChips",
        "sama", "gdb", "karpathy", "AnthropicAI", "OpenAI", "AravSrinivas", "natfriedman",
        "leopoldasch", "alexandr_wang", "victor207755822", "sainingxie", "shengjia_zhao",
        "NickTimiraos", "josephwang", "biancoresearch", "LynAldenContact", "MacroAlf",
        "robin_j_brooks", "Brad_Setser", "darioperkins", "elerianm",
        "BillAckman", "michaeljburry", "DanielSLoeb1", "GavinSBaker", "altcap",
        "DanielTNiles", "RealJimChanos",
        "HindenburgRes", "CitronResearch", "sprucepointcap", "ScorpionFund", "Bleecker__St",
        "Lordshipstrade",
        "JKempEnergy", "Rory_Johnston", "HFI_Research", "EnergyAspects", "Amena__Bakr",
        "quakes99", "BambroughKevin",
        "zephyr_z9", "ParadisLabs", "bubbleboi", "TBU12345678", "crux_capital_",
        "The_AI_Investor", "midnight_captl", "techfund1", "GHadjia", "mvcinvesting",
        "Mayhem4Markets", "marketplunger1", "QQ_Timmy", "jukan05", "restructuring__",
        "ByrneHobart", "TaeKim_Tech",
    ]
}

# Generic sell-side noise senders (BTG, BBI etc) — filter.py mirror.
EMAIL_SENDER_DROP = [
    "btg pactual", "macro sales itaú", "macro sales itau", "itaú bba", "itau bba",
    "bradesco bbi", "safra ", "xp investimentos", "research xp", "ibba daily",
    "marcio osako", "bruno mendonca", "marcelo mizrahi", "marcelo motta",
]
# Brazil-only / non-TMT subject blacklist (subset of filter.py SUBJECT_DROP).
EMAIL_SUBJECT_DROP = [
    "brasil", "brazilian", "brasileira", "bz:", "bz ", "ibovespa", "ibov",
    "copom", "focus", "fenabrave", "ipca", "igp", "pnad", "caged", "bcb", "selic",
    "clipping", "daily clipping", "latam daily",
    "preços dos ativos", "vol de opções", "rateio", "rolagem", "cotas",
]


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


# ── /api/repo/feed — ranked inbox view (Gmail-style two-column) ──────────
def _parse_ts(s: str) -> datetime | None:
    """Parse the various tweet/email timestamp shapes back to UTC datetime."""
    if not s:
        return None
    try:
        # ISO 8601 with or without timezone
        s2 = s.replace(" ", "T")
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        d = datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _tweet_relevance(row: dict, now: datetime) -> float | None:
    """Score a tweet on a roughly 0–20 scale; returns None to drop entirely."""
    handle = (row.get("handle") or "").lower()
    if handle in DROP_HANDLES:
        return None
    text = row.get("text") or ""

    # Engagement (log-scaled — compresses 10x viral tweets to 2-3x score)
    likes = row.get("like_count") or 0
    rts = row.get("retweet_count") or 0
    views = row.get("view_count") or 0
    eng = math.log1p(likes + 2 * rts + views / 200) * 1.1

    # Tier-1 voice boost (Dylan Patel, Jensen, Cramer, etc.)
    tier_boost = 3.5 if handle in TIER1 else 0.0

    # Recency decay (full credit if < 6h old, halves every 24h)
    ts = _parse_ts(row.get("created_at") or "")
    if ts is None:
        recency = 0.0
    else:
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
        recency = 4.0 / (1 + age_h / 24.0)

    # Universe ticker bonus
    tickers = universe.match_text(text, kind="tweet")
    ticker_bonus = 3.0 if tickers else 0.0
    if "ANTHROPIC" in tickers or "OPENAI" in tickers:
        ticker_bonus += 1.0  # AI lab mentions get extra boost

    return eng + tier_boost + recency + ticker_bonus, tickers


def _email_relevance(e: dict, now: datetime) -> tuple[float, list[str]] | None:
    sender = ((e.get("sender") or "") + " " + (e.get("sender_email") or "")).lower()
    subj = (e.get("subject") or "").lower()
    folder = (e.get("folder") or "").lower()

    # Folder drops (sent, deleted, junk, drafts)
    for fd in ("/sent", "/junk", "/deleted", "/drafts", "sent items"):
        if fd in folder:
            return None
    # Sender drops (generic clipping)
    if any(sd in sender for sd in EMAIL_SENDER_DROP):
        return None
    # Subject drops (Brazil/non-TMT)
    if any(bad in subj for bad in EMAIL_SUBJECT_DROP):
        return None

    ts = _parse_ts(e.get("date") or "")
    if ts is None:
        recency = 0.0
    else:
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
        recency = 5.0 / (1 + age_h / 12.0)   # emails decay faster than tweets

    haystack = subj + " " + (e.get("body_preview") or "")
    tickers = universe.match_text(haystack, kind="email")
    ticker_bonus = 4.0 if tickers else 0.0

    return recency + ticker_bonus + 1.0, tickers


@router.get("/repo/feed")
def repo_feed(
    hours: int = Query(48, ge=1, le=240, description="Tweet lookback"),
    tweet_limit: int = Query(60, ge=1, le=300),
    email_limit: int = Query(60, ge=1, le=300),
) -> dict[str, Any]:
    """Ranked inbox: top tickers + tweets (relevance) + emails (relevance)."""
    now = datetime.now(timezone.utc)

    # ── Tweets ──────────────────────────────────────────────────────────
    tweet_rows: list[dict] = []
    if TWEETS_DB.exists():
        with _con() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT tweet_id, handle, author_name, category, created_at, text, url,
                       is_quote, like_count, retweet_count, reply_count, view_count
                FROM tweets
                WHERE created_at >= datetime('now', ?)
                  AND is_retweet = 0
                  AND is_reply = 0
                ORDER BY datetime(created_at) DESC
                """,
                (f"-{hours} hours",),
            ).fetchall()
        for r in rows:
            scored = _tweet_relevance(dict(r), now)
            if scored is None:
                continue
            score, tickers = scored
            tweet_rows.append({
                "score": round(score, 2),
                "id": r["tweet_id"],
                "ts": r["created_at"],
                "handle": r["handle"],
                "author": r["author_name"],
                "category": r["category"],
                "text": r["text"] or "",
                "url": r["url"],
                "is_quote": bool(r["is_quote"]),
                "is_tier1": (r["handle"] or "").lower() in TIER1,
                "likes": r["like_count"] or 0,
                "retweets": r["retweet_count"] or 0,
                "replies": r["reply_count"] or 0,
                "views": r["view_count"] or 0,
                "tickers": tickers,
            })
        tweet_rows.sort(key=lambda x: x["score"], reverse=True)

    # ── Emails ──────────────────────────────────────────────────────────
    email_rows: list[dict] = []
    cache_present = EMAILS_CACHE.exists()
    if cache_present:
        for e in _load_email_cache():
            scored = _email_relevance(e, now)
            if scored is None:
                continue
            score, tickers = scored
            email_rows.append({
                "score": round(score, 2),
                "id": e.get("entry_id") or "",
                "ts": e.get("date") or "",
                "sender": e.get("sender") or "",
                "sender_email": e.get("sender_email") or "",
                "subject": e.get("subject") or "",
                "preview": e.get("body_preview") or "",
                "folder": e.get("folder") or "",
                "tickers": tickers,
            })
        email_rows.sort(key=lambda x: x["score"], reverse=True)

    # ── Top tickers (across tweets + emails) ────────────────────────────
    ticker_counter: Counter[str] = Counter()
    for row in tweet_rows + email_rows:
        for t in row["tickers"]:
            ticker_counter[t] += 1
    top_tickers = [
        {"ticker": t, "n": n} for t, n in ticker_counter.most_common(15)
    ]

    # ── Top "themes" — simple high-frequency capitalized words / hashtags ──
    theme_counter: Counter[str] = Counter()
    STOP = {
        "the", "and", "for", "with", "from", "this", "that", "are", "was", "you",
        "your", "his", "her", "have", "has", "will", "but", "all", "new", "just",
        "now", "out", "get", "got", "still", "more", "via", "into", "after", "over",
        "they", "their", "there", "what", "when", "than", "then", "been", "were",
        "had", "would", "could", "should", "via", "rt", "amp", "https", "http",
    }
    for r in tweet_rows[:200]:
        for w in re.findall(r"[A-Za-z][A-Za-z']{3,}", r["text"]):
            wl = w.lower()
            if wl in STOP:
                continue
            theme_counter[wl] += 1
    top_themes = [
        {"theme": t, "n": n} for t, n in theme_counter.most_common(12)
    ]

    return {
        "now": now.isoformat(timespec="seconds"),
        "hours": hours,
        "top_tickers": top_tickers,
        "top_themes": top_themes,
        "tweets": tweet_rows[:tweet_limit],
        "emails": email_rows[:email_limit],
        "tweet_pool": len(tweet_rows),
        "email_pool": len(email_rows),
        "emails_cache_present": cache_present,
    }
