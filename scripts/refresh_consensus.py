"""Nightly snapshot of BBG consensus → data/consensus.json.

Pulls BEST_* fields for every ticker in config/tickers.yaml that has
`in_valuation: true` or has a `bbg_ticker` set. Writes to data/consensus.json
so the frontend can render the Valuation tab and the drawer's Consensus pane
even when BBG (or the backend) is unreachable.

Schedule via Windows Task Scheduler (recommended: daily 06:00 weekdays):
    schtasks /create /tn "Portfolio Consensus Refresh" /tr "py -3.11 C:\\Users\\felipe.monteiro\\repos\\Portfolio-dashboard\\scripts\\refresh_consensus.py" /sc daily /st 06:00 /f
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import bbg_adapter, universe  # noqa: E402

OUT_PATH = ROOT / "data" / "consensus.json"
FIELDS = [
    "BEST_EPS",
    "BEST_SALES",
    "BEST_EBITDA",
    "BEST_TARGET_PRICE",
    "BEST_ANALYST_RATING",
    "PE_RATIO",
]


def main() -> int:
    if not bbg_adapter.is_available():
        print(f"BBG unreachable: {bbg_adapter.import_error() or 'no response'}", file=sys.stderr)
        return 1

    universe.load()
    entries = universe.get_entries()
    targets = [e for e in entries if not e.get("pseudo") and e.get("bbg_ticker")]
    bbg_tickers = [e["bbg_ticker"] for e in targets]
    print(f"Pulling {len(bbg_tickers)} tickers × {len(FIELDS)} fields…", file=sys.stderr)

    try:
        df = bbg_adapter.bdp(bbg_tickers, FIELDS)
    except Exception as exc:
        print(f"bdp failed: {exc}", file=sys.stderr)
        return 2

    snapshot = {"updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "tickers": {}}
    bbg_to_local = {e["bbg_ticker"]: e["ticker"] for e in targets}
    for bbg_t, row in df.iterrows():
        local = bbg_to_local.get(bbg_t)
        if not local:
            continue
        payload = {f.lower(): (float(row[f]) if row.get(f) is not None and row.get(f) == row.get(f) else None)
                   for f in FIELDS if f in df.columns}
        snapshot["tickers"][local] = {"fields": payload}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(snapshot['tickers'])} tickers to {OUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
