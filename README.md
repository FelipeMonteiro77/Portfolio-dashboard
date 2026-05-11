# Portfolio Dashboard v2

Live, click-through portfolio dashboard combining:
- **Live prices** — BBG `bdp(PX_LAST)` via the Capstone LAN server, with a Yahoo fallback.
- **Live consensus** — BBG `BEST_*` fields refreshed nightly into `data/consensus.json`.
- **Click-a-ticker drawer** — opens a right-side panel with recent Tweets (from the local 24h corpus), Outlook emails (cached locally), the consensus snapshot, and a 3-month price chart.
- **Easy ticker add** — `+ Add Ticker` modal POSTs to `/api/tickers`, which appends to `config/tickers.yaml` and reloads.

## Tabs

- **Overview** — portfolio weight evolution, cumulative P&L, allocation breakdown
- **Snapshot** — latest holdings, sector exposure, geographic breakdown
- **Ticker** — individual deep-dive (price + weight timeline)
- **Heatmap** — weight heatmap across all positions and dates
- **Price Analytics** — high/low, drawdown, volatility, normalized comparison
- **Risk & Analytics** — concentration (HHI), geographic, long/short
- **Valuation** — forward P/E, EPS growth, Capstone vs Consensus
- **Screen** — 60+ watchlist with RSI(14), 52-week ranges, news feed

## Two modes

| Mode | URL | What works |
|---|---|---|
| **Local rich** | `http://127.0.0.1:8765/` (run `scripts\start.bat`) | Everything — live BBG, drawer with Emails + Tweets + Consensus + Chart, Add-Ticker |
| **GH Pages fallback** | `https://felipemonteiro77.github.io/Portfolio-dashboard/` | Yahoo prices, last snapshotted consensus, the original analytics tabs. Drawer disabled (no BBG/Outlook/SQLite reachable from a public host). |

## Quick start (local)

```powershell
# install dependencies (once)
py -3.11 -m pip install -r backend/requirements.txt

# run the dashboard
scripts\start.bat
```

Open http://127.0.0.1:8765 and watch the mode pill in the header — `BBG · HH:MM` when the LAN server is reachable, otherwise `YAHOO · HH:MM`.

## Adding a ticker

Either:
1. Click **＋ Add Ticker** in the header (only visible when the backend is up).
2. Or edit `config/tickers.yaml` directly and `curl -X POST http://127.0.0.1:8765/api/tickers/reload`.

The same YAML drives the watchlist, the consensus universe, and the email/tweet alias lookups for click-through.

## Layout

```
.
├── index.html                       # canonical frontend (GH Pages + backend both serve this)
├── css/extensions.css               # v2 styles (drawer, ticker strip, modal)
├── js/
│   ├── dashboard-extensions.js      # backend probe + ticker strip + 5-min price loop
│   ├── ticker-drawer.js             # right-side drawer (Emails/Tweets/Consensus/Chart)
│   └── ticker-config.js             # "+ Add Ticker" modal
├── data/                            # consensus.json + prices.json snapshots
├── config/tickers.yaml              # SINGLE source of truth for the universe
├── backend/                         # FastAPI server (server.py, routes/, bbg_adapter.py, universe.py)
└── scripts/
    ├── start.bat                    # launch backend + open browser
    ├── refresh_consensus.py         # daily BBG snapshot → data/consensus.json
    └── refresh_prices.py            # Yahoo snapshot for GH Pages fallback
```

## Scheduling

**Consensus** (nightly, requires BBG LAN):
```
schtasks /create /tn "Portfolio Consensus Refresh" ^
  /tr "py -3.11 C:\Users\felipe.monteiro\repos\Portfolio-dashboard\scripts\refresh_consensus.py" ^
  /sc daily /st 06:00 /f
```

**Prices** (every N minutes during US hours, Yahoo-only — for GH Pages fallback): the existing `.github/workflows/update-prices.yml` already runs at 13:00 + 21:00 UTC. Switch it to call `scripts/refresh_prices.py` so it shares the YAML config.
