"""Portfolio Dashboard v2 — FastAPI entry point.

Run with:
    python -m uvicorn backend.server:app --host 127.0.0.1 --port 8765 --reload

Serves:
    /                   → frontend/index.html
    /static/*           → frontend/{css,js,data}/*
    /api/health         → backend availability probe
    /api/tickers        → universe (GET) + add (POST)
    /api/prices         → live BBG/Yahoo snapshot
    /api/consensus      → BBG BEST_* fields per ticker
    /api/emails         → Outlook search by ticker (cached)
    /api/tweets         → local SQLite FTS5 by ticker
    /api/chart          → intraday/daily OHLC
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import chart, consensus, emails, health, news, prices, tickers, tweets
from . import universe

ROOT = Path(__file__).resolve().parent.parent
# Frontend assets live at the repo root so GH Pages and the local server
# can both serve the same canonical index.html with no copy/symlink dance.
FRONTEND_DIR = ROOT

app = FastAPI(title="Portfolio Dashboard v2", version="2.0.0")

# CORS: dashboard is single-origin in normal mode, but GH Pages fallback
# (degraded mode) loads from a different host. Locked to localhost to be safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1", "https://felipemonteiro77.github.io"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _load_universe():
    universe.load()


# Routes
app.include_router(health.router, prefix="/api")
app.include_router(tickers.router, prefix="/api")
app.include_router(prices.router, prefix="/api")
app.include_router(consensus.router, prefix="/api")
app.include_router(emails.router, prefix="/api")
app.include_router(tweets.router, prefix="/api")
app.include_router(chart.router, prefix="/api")
app.include_router(news.router, prefix="/api")


# Static frontend
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
if (FRONTEND_DIR / "data").exists():
    app.mount("/data", StaticFiles(directory=FRONTEND_DIR / "data"), name="data")


@app.get("/")
def root():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return {"error": f"frontend/index.html not found at {index}"}
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8766, reload=True)
