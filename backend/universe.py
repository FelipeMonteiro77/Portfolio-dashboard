"""Load config/tickers.yaml into a singleton in-memory universe.

Resolves search aliases for emails and tweets. Provides helpers the route
modules use to translate "click NVDA" into the right Outlook / SQLite query.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "tickers.yaml"

_lock = threading.RLock()
_state: dict[str, Any] = {
    "loaded_at": None,
    "entries": [],
    "by_ticker": {},
    "tweet_patterns": {},   # ticker -> compiled regex (for tweet match)
    "email_patterns": {},   # ticker -> compiled regex (for email match)
}


def _normalize(entry: dict) -> dict:
    """Fill defaults so routes can rely on a uniform shape."""
    e = dict(entry)
    # YAML 1.1 booleanish tokens (ON, OFF, NO, YES, etc.) get parsed as bool —
    # coerce back to string. Same for numeric-looking tickers.
    e["ticker"] = str(e["ticker"])
    t = e["ticker"]
    e.setdefault("bbg_ticker", f"{t} US Equity")
    e.setdefault("name", t)
    e.setdefault("sector", "Other")
    e.setdefault("in_screen", True)
    e.setdefault("in_valuation", bool(e.get("capstone_eps")))
    e.setdefault("pseudo", False)
    e.setdefault("tweet_cashtag_only", False)
    aliases = e.get("search_aliases") or {}
    e["search_aliases"] = {
        "email": list(aliases.get("email") or []),
        "tweet": list(aliases.get("tweet") or []),
    }
    return e


def load() -> dict:
    """Re-read config/tickers.yaml from disk and rebuild lookups."""
    with _lock:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw = data.get("universe") or []
        entries = [_normalize(e) for e in raw]
        _state["entries"] = entries
        _state["by_ticker"] = {e["ticker"]: e for e in entries}
        _state["tweet_patterns"] = _compile_patterns(entries, kind="tweet")
        _state["email_patterns"] = _compile_patterns(entries, kind="email")
        _state["loaded_at"] = os.path.getmtime(CONFIG_PATH)
        return _state


def _compile_patterns(entries: list[dict], kind: str) -> dict[str, re.Pattern]:
    """Compile per-ticker regex patterns for the news matcher.

    - kind="tweet": short / common-word tickers require $ cashtag; longer ones
                    also match bare word-boundary symbols. Plus alias substrings.
    - kind="email": uppercase word-boundary tickers (case-sensitive) plus
                    alias substrings (case-insensitive substrings, run separately).
    Mirrors the logic from company-specific/twitter_match.py + filter.py."""
    out: dict[str, re.Pattern] = {}
    for e in entries:
        t = e["ticker"]
        if e.get("pseudo"):
            continue
        if t == "CHIP11.SA":
            pat = re.compile(r"\$?\bCHIP11(?:\.SA)?\b", re.I if kind == "tweet" else 0)
        elif kind == "tweet" and e.get("tweet_cashtag_only"):
            # Common-word tickers (BE, ON, FN, BX, ...) require an explicit cashtag
            pat = re.compile(r"\$" + re.escape(t) + r"\b", re.I)
        elif kind == "tweet":
            # Unambiguous symbols: match cashtag OR bare uppercase word boundary
            pat = re.compile(r"(?:\$" + re.escape(t) + r"|\b" + re.escape(t) + r")\b", re.I)
        else:  # email: case-sensitive word boundary, no cashtag
            pat = re.compile(r"\b" + re.escape(t) + r"\b")
        out[t] = pat
    return out


def match_text(text: str, kind: str = "tweet") -> list[str]:
    """Return list of universe tickers mentioned in `text` (deduped, sorted)."""
    if not text:
        return []
    with _lock:
        if not _state["entries"]:
            load()
        patterns = _state["tweet_patterns"] if kind == "tweet" else _state["email_patterns"]
        entries = _state["entries"]

    hits: set[str] = set()
    lower = text.lower()
    # 1) Regex on tickers / cashtags
    for t, pat in patterns.items():
        if pat.search(text):
            hits.add(t)
    # 2) Alias substring fallback — but only for *unambiguous* aliases.
    #    Skip 1–3 char aliases, the bare ticker, and the cashtag form: those
    #    are already covered by the regex and would otherwise produce false
    #    positives ("$ON" → "on" → matches "Jensen on stage").
    for e in entries:
        t = e["ticker"]
        if t in hits:
            continue
        aliases = e["search_aliases"].get(kind, [])
        for a in aliases:
            a_clean = a.lstrip("$").strip()
            if len(a_clean) < 4:
                continue
            if a_clean.upper() == t.upper():
                continue
            if a_clean.lower() in lower:
                hits.add(t)
                break
    return sorted(hits)


def get_entries() -> list[dict]:
    with _lock:
        if not _state["entries"]:
            load()
        return list(_state["entries"])


def get(ticker: str) -> dict | None:
    with _lock:
        if not _state["entries"]:
            load()
        return _state["by_ticker"].get(ticker)


def email_aliases(ticker: str) -> list[str]:
    """List of substrings to OR-search Outlook for this ticker.

    Falls back to the ticker symbol itself if no aliases configured."""
    e = get(ticker)
    if not e:
        return [ticker]
    out = list(e["search_aliases"]["email"])
    if not e.get("pseudo"):
        out.append(ticker)
    return list(dict.fromkeys(out))  # dedupe, preserve order


def tweet_aliases(ticker: str) -> list[str]:
    """List of FTS5 tokens to OR-search the tweet corpus.

    Honors `tweet_cashtag_only` for tickers that collide with English words."""
    e = get(ticker)
    if not e:
        return [f"${ticker}"]
    out = list(e["search_aliases"]["tweet"])
    if not e.get("pseudo"):
        if e.get("tweet_cashtag_only"):
            if f"${ticker}" not in out:
                out.append(f"${ticker}")
        else:
            if ticker not in out:
                out.append(ticker)
            if f"${ticker}" not in out:
                out.append(f"${ticker}")
    return list(dict.fromkeys(out))


def append(entry: dict) -> dict:
    """Append a new ticker block to config/tickers.yaml and reload.

    Writes a *minimal* YAML block; preserves the rest of the file verbatim.
    Returns the normalized entry."""
    with _lock:
        ticker = entry["ticker"]
        if get(ticker):
            raise ValueError(f"ticker {ticker} already exists")
        normalized = _normalize(entry)
        # Append to file (don't rewrite — preserves comments/ordering).
        block = _format_block(normalized)
        with open(CONFIG_PATH, "a", encoding="utf-8") as f:
            f.write("\n  # ─── Added via API ───\n")
            f.write(block)
        load()
        return normalized


def _format_block(e: dict) -> str:
    """Render one entry as a single-line YAML flow-mapping block.

    Mirrors the style used in the hand-written tickers.yaml."""
    parts = [f'ticker: {e["ticker"]}']
    if e.get("bbg_ticker") != f'{e["ticker"]} US Equity':
        parts.append(f'bbg_ticker: {e["bbg_ticker"]}')
    parts.append(f'name: {_yaml_str(e["name"])}')
    parts.append(f'sector: {_yaml_str(e["sector"])}')
    if e.get("in_valuation"):
        parts.append("in_valuation: true")
    if e.get("tweet_cashtag_only"):
        parts.append("tweet_cashtag_only: true")
    if e.get("pseudo"):
        parts.append("pseudo: true")
    em = e["search_aliases"]["email"]
    tw = e["search_aliases"]["tweet"]
    parts.append(
        "search_aliases: {"
        f'email: [{", ".join(_yaml_str(s) for s in em)}], '
        f'tweet: [{", ".join(_yaml_str(s) for s in tw)}]'
        "}"
    )
    return "  - {" + ", ".join(parts) + "}\n"


def _yaml_str(s: str) -> str:
    """Quote a string for inline YAML if it contains special chars."""
    if any(c in s for c in [":", ",", "[", "]", "{", "}", "&", "*", "#", '"', "'"]):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    return s
