"""Thin wrapper around the Capstone BBG HTTP API.

Imports the existing `bloomberg.py` from C:/Users/felipe.monteiro/OneDrive/BBG completo/bloomberg_api/.
Falls back to None when the LAN server (10.10.60.104) is unreachable so
routes can transparently degrade to Yahoo / cached snapshots.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BBG_LIB_PATH = Path(r"C:/Users/felipe.monteiro/OneDrive/BBG completo/bloomberg_api")
if str(BBG_LIB_PATH) not in sys.path:
    sys.path.insert(0, str(BBG_LIB_PATH))

try:
    import bloomberg as _bbg  # type: ignore
    _IMPORT_ERROR: str | None = None
except Exception as exc:
    _bbg = None
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def is_available() -> bool:
    """Probe the BBG HTTP server with a tiny bdp call."""
    if _bbg is None:
        return False
    try:
        df = _bbg.bdp(["SPX Index"], ["PX_LAST"])
        return df is not None and not df.empty
    except Exception:
        return False


def bdp(tickers: list[str], fields: list[str]) -> Any:
    """Snapshot reference data."""
    if _bbg is None:
        raise RuntimeError(f"BBG library unavailable: {_IMPORT_ERROR}")
    return _bbg.bdp(tickers, fields)


def bdh(tickers: list[str], fields: list[str], start: str, end: str) -> Any:
    if _bbg is None:
        raise RuntimeError(f"BBG library unavailable: {_IMPORT_ERROR}")
    return _bbg.bdh(tickers, fields, start, end)


def bds(ticker: str, field: str) -> Any:
    if _bbg is None:
        raise RuntimeError(f"BBG library unavailable: {_IMPORT_ERROR}")
    return _bbg.bds(ticker, field)


def import_error() -> str | None:
    return _IMPORT_ERROR
