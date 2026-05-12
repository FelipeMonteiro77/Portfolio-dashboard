/* ════════════════════════════════════════════════════════════════════════
 * Portfolio Dashboard v2 — extensions runtime
 *
 * Responsibilities:
 *   1. Probe /api/health to determine "live" (backend up) vs "offline" mode.
 *   2. Inject a header mode-pill + "+ Add Ticker" button (when live).
 *   3. Inject a scrolling ticker strip above the tab bar.
 *   4. Poll /api/prices every 5 minutes (or fall back to existing Yahoo flow).
 *   5. Wire row-clicks on tables to open the v2 ticker drawer.
 *   6. Expose a small window.V2 namespace consumed by ticker-drawer.js /
 *      ticker-config.js.
 *
 * No-ops cleanly when /api/health is unreachable (GH Pages mode).
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const REFRESH_MS = 5 * 60 * 1000;     // 5 minutes — per user preference
  const STRIP_TICKERS = [
    'NVDA','AVGO','TSM','AMD','AAPL','GOOG','META','AMZN','MSFT',
    'LITE','COHR','MRVL','ANET','UBER','SPOT','NFLX','VRT','GEV',
  ];

  const state = {
    mode: 'probing',              // 'live' | 'cached' | 'offline' | 'probing'
    health: null,
    prevPrices: {},               // ticker -> last seen px (for flash)
    refreshTimer: null,
    universe: null,
  };

  // Expose a stable namespace for sibling modules.
  window.V2 = window.V2 || {};
  window.V2.state = state;
  window.V2.openDrawer = (t) => console.warn('drawer module not loaded yet', t);

  // ── Yahoo CORS shim ───────────────────────────────────────────────────
  // The original index.html fetches query1.finance.yahoo.com directly from the
  // browser. That works on file:// or github.io, but localhost gets CORS-blocked.
  // We patch window.fetch so any Yahoo chart URL is transparently rewritten to
  // our /api/chart proxy, which makes the same call server-side.
  (function installYahooShim() {
    const realFetch = window.fetch.bind(window);
    window.fetch = function (url, opts) {
      try {
        const u = (typeof url === 'string') ? url : (url && url.url) || '';
        if (u.includes('query1.finance.yahoo.com/v8/finance/chart/')) {
          // Extract symbol + query params and rewrite.
          const m = u.match(/\/chart\/([^?]+)\?(.*)$/);
          if (m) {
            const sym = decodeURIComponent(m[1]);
            const qs = new URLSearchParams(m[2]);
            const range_ = qs.get('range') || '1mo';
            const interval = qs.get('interval') || '1d';
            // Map to /api/chart, then wrap the response in the same Yahoo shape
            // the original code expects.
            return realFetch(`/api/chart?ticker=${encodeURIComponent(sym)}&range=${range_}&interval=${interval}`)
              .then(r => r.ok ? r.json() : Promise.reject(new Error('chart ' + r.status)))
              .then(d => ({
                ok: true,
                json: async () => ({
                  chart: {
                    result: [{
                      meta: {
                        regularMarketPrice: d.close?.[d.close.length - 1] ?? null,
                        chartPreviousClose: d.close?.[d.close.length - 2] ?? null,
                        currency: d.currency,
                      },
                      timestamp: d.timestamps,
                      indicators: { quote: [{ close: d.close, open: d.open, high: d.high, low: d.low, volume: d.volume }] },
                    }],
                  },
                }),
              }))
              .catch(err => ({ ok: false, status: 502, json: async () => ({ error: String(err) }) }));
          }
        }
      } catch (e) { /* fall through to real fetch */ }
      return realFetch(url, opts);
    };
  })();

  // ── Boot ──────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(boot, 50);  // let the original dashboard finish its initial render
  });

  async function boot() {
    document.body.classList.add('v2-extensions-active');
    injectHeaderUi();
    injectTickerStrip();
    await probeHealth();
    wireRowClicks();
    if (state.mode !== 'offline') {
      await loadUniverse();
      await refreshPrices();
      state.refreshTimer = setInterval(() => {
        if (document.visibilityState === 'visible') refreshPrices();
      }, REFRESH_MS);
    } else {
      // Offline: fill the ticker strip from the existing SCREEN_WL seed prices
      seedStripFromOfflineData();
    }
  }

  // ── Header UI ─────────────────────────────────────────────────────────
  function injectHeaderUi() {
    const badges = document.getElementById('hdr-badges');
    if (!badges) return;
    const pill = document.createElement('span');
    pill.id = 'v2-mode-pill';
    pill.className = 'v2-mode-pill offline';
    pill.title = 'Click to refresh now';
    pill.style.cursor = 'pointer';
    pill.innerHTML = '<span class="dot"></span><span class="lbl">probing…</span>';
    pill.addEventListener('click', () => {
      if (state.mode === 'offline') {
        probeHealth().then(() => state.mode !== 'offline' && refreshPrices());
      } else {
        refreshPrices();
      }
    });
    badges.appendChild(pill);

    const addBtn = document.createElement('button');
    addBtn.className = 'v2-add-btn';
    addBtn.id = 'v2-add-btn';
    addBtn.innerHTML = '＋ Add Ticker';
    addBtn.style.display = 'none';
    addBtn.addEventListener('click', () => {
      if (window.V2.openAddTicker) window.V2.openAddTicker();
    });
    const refreshBtn = document.getElementById('refresh-btn');
    refreshBtn?.parentElement?.insertBefore(addBtn, refreshBtn);
  }

  function setMode(mode, label) {
    state.mode = mode;
    const pill = document.getElementById('v2-mode-pill');
    if (pill) {
      pill.className = `v2-mode-pill ${mode}`;
      pill.querySelector('.lbl').textContent = label || mode;
    }
    const addBtn = document.getElementById('v2-add-btn');
    if (addBtn) addBtn.style.display = (mode === 'live') ? '' : 'none';
  }

  // ── Backend probe ─────────────────────────────────────────────────────
  async function probeHealth() {
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      if (!r.ok) throw new Error('health ' + r.status);
      const h = await r.json();
      state.health = h;
      const tags = [];
      if (h.bbg?.available) tags.push('BBG');
      else tags.push('Yahoo');
      if (h.tweets?.available) tags.push(`tweets ${h.tweets.rows}`);
      if (h.outlook?.available) tags.push('mail');
      setMode('live', tags.join(' · '));
    } catch (e) {
      setMode('offline', 'no backend');
      console.info('[v2] /api/health unreachable — running in GH-Pages fallback mode');
    }
  }

  // ── Universe sync ─────────────────────────────────────────────────────
  async function loadUniverse() {
    try {
      const r = await fetch('/api/tickers');
      if (!r.ok) return;
      const data = await r.json();
      state.universe = data.universe;
      state.tickerSet = new Set(data.universe.map(u => u.ticker));
      window.V2.universe = data.universe;
    } catch (e) { /* ignore */ }
  }
  window.V2.loadUniverse = loadUniverse;

  // ── Ticker strip ──────────────────────────────────────────────────────
  function injectTickerStrip() {
    const bar = document.querySelector('.tab-bar');
    if (!bar) return;
    const strip = document.createElement('div');
    strip.className = 'v2-ticker-strip';
    strip.id = 'v2-ticker-strip';
    strip.innerHTML = `<div class="v2-ticker-strip-track" id="v2-strip-track">
      ${STRIP_TICKERS.map(t => stripCell(t, null, null)).join('')}
    </div>`;
    bar.parentElement.insertBefore(strip, bar);
  }

  function stripCell(ticker, px, chg) {
    const dir = (chg == null) ? 'flat' : (chg >= 0 ? 'up' : 'down');
    const sign = (chg != null && chg > 0) ? '+' : '';
    const pxStr = (px == null) ? '—' : px.toFixed(2);
    const chgStr = (chg == null) ? '' : ` ${sign}${chg.toFixed(2)}%`;
    return `<span class="v2-ticker-cell" data-v2-strip="${ticker}">
      <span class="sym">${ticker}</span>
      <span class="px">${pxStr}</span>
      <span class="chg ${dir}">${chgStr}</span>
    </span>`;
  }

  function paintStripCell(ticker, px, chg) {
    const prev = state.prevPrices[ticker];
    const cells = document.querySelectorAll(`[data-v2-strip="${cssEsc(ticker)}"]`);
    cells.forEach(cell => {
      cell.outerHTML = stripCell(ticker, px, chg);
    });
    // Re-query — DOM was replaced
    const fresh = document.querySelectorAll(`[data-v2-strip="${cssEsc(ticker)}"]`);
    if (prev != null && px != null && prev !== px) {
      fresh.forEach(el => {
        el.classList.add(px > prev ? 'v2-flash-up' : 'v2-flash-down');
        setTimeout(() => el.classList.remove('v2-flash-up','v2-flash-down'), 900);
      });
    }
    state.prevPrices[ticker] = px;
  }

  function seedStripFromOfflineData() {
    // Pull from the existing SCREEN_WL constant baked into index.html
    const wl = window.SCREEN_WL || [];
    const lookup = Object.fromEntries(wl.map(r => [r.t, r]));
    STRIP_TICKERS.forEach(t => {
      const row = lookup[t];
      if (row) paintStripCell(t, row.p, row.chg);
    });
  }

  // ── Price refresh loop ────────────────────────────────────────────────
  async function refreshPrices() {
    try {
      const r = await fetch(`/api/prices?tickers=${encodeURIComponent(STRIP_TICKERS.join(','))}`);
      if (!r.ok) throw new Error('prices ' + r.status);
      const data = await r.json();
      Object.entries(data.prices || {}).forEach(([t, info]) => {
        paintStripCell(t, info.price, info.chg_pct);
      });
      // Update mode pill with source
      if (state.mode === 'live' && data.source) {
        const pill = document.getElementById('v2-mode-pill');
        if (pill) {
          const ts = new Date().toLocaleTimeString('en-US', {hour12:false, hour:'2-digit', minute:'2-digit'});
          pill.querySelector('.lbl').textContent = `${data.source.toUpperCase()} · ${ts}`;
        }
      }
    } catch (e) {
      console.warn('[v2] price refresh failed', e);
    }
  }

  // ── Row-click wiring ──────────────────────────────────────────────────
  // Strategy: match strictly against the known universe set. Walk each TR's
  // cells (and any child elements with a `data-ticker` attribute) and pick the
  // first one whose text matches a universe ticker. No regex heuristics — this
  // avoids false positives on cells like "L"/"S" in the Snapshot Side column.
  function wireRowClicks() {
    document.addEventListener('click', (ev) => {
      if (state.mode === 'offline') return;
      // Don't hijack clicks on actual links/buttons inside a row.
      if (ev.target.closest('a, button')) return;
      const row = ev.target.closest('tr');
      if (!row) return;

      // Tagged row wins
      let ticker = row.getAttribute('data-v2-ticker');
      if (!ticker && state.universe) {
        const set = state.tickerSet || (state.tickerSet = new Set(state.universe.map(u => u.ticker)));
        // Walk visible cell text — first universe match wins.
        for (const td of row.children) {
          const txt = (td.textContent || '').trim();
          if (set.has(txt)) { ticker = txt; break; }
        }
      }
      if (!ticker) return;
      ev.preventDefault();
      if (window.V2.openDrawer) window.V2.openDrawer(ticker);
    }, true);
  }

  function cssEsc(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, c => `\\${c}`);
  }

  // Expose helpers for sibling modules
  window.V2.paintStripCell = paintStripCell;
  window.V2.refreshPrices = refreshPrices;
})();
