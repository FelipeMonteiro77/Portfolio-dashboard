/* ════════════════════════════════════════════════════════════════════════
 * Ticker drawer — slide-in right panel with 4 sub-tabs.
 *   Emails    → /api/emails?ticker=…
 *   Tweets    → /api/tweets?ticker=…
 *   Consensus → /api/consensus?ticker=…
 *   Chart     → /api/chart?ticker=…   (1mo daily, Plotly line)
 *
 * Opens via window.V2.openDrawer('NVDA'). Closes on backdrop click, X, ESC.
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const STATE = {
    ticker: null,
    tab: 'tweets',         // default: tweets are fastest to load
    chartRendered: false,
  };

  // ── DOM ───────────────────────────────────────────────────────────────
  const backdrop = document.createElement('div');
  backdrop.className = 'v2-drawer-backdrop';
  backdrop.addEventListener('click', close);

  const drawer = document.createElement('aside');
  drawer.className = 'v2-drawer';
  drawer.innerHTML = `
    <div class="v2-drawer-header">
      <div class="v2-drawer-title">
        <span class="v2-drawer-ticker" id="v2d-ticker">—</span>
        <span class="v2-drawer-name" id="v2d-name"></span>
      </div>
      <button class="v2-drawer-close" id="v2d-close" aria-label="Close">×</button>
    </div>
    <div class="v2-drawer-px" id="v2d-px">
      <span class="price" id="v2d-price">—</span>
      <span class="chg flat" id="v2d-chg"></span>
      <span class="meta" id="v2d-meta"></span>
    </div>
    <div class="v2-drawer-tabs">
      <div class="v2-drawer-tab" data-pane="tweets">Tweets</div>
      <div class="v2-drawer-tab" data-pane="emails">Emails</div>
      <div class="v2-drawer-tab" data-pane="consensus">Consensus</div>
      <div class="v2-drawer-tab" data-pane="chart">Chart</div>
    </div>
    <div class="v2-drawer-body">
      <div class="v2-drawer-pane" data-pane="tweets" id="v2d-pane-tweets"></div>
      <div class="v2-drawer-pane" data-pane="emails" id="v2d-pane-emails"></div>
      <div class="v2-drawer-pane" data-pane="consensus" id="v2d-pane-consensus"></div>
      <div class="v2-drawer-pane" data-pane="chart" id="v2d-pane-chart">
        <div class="v2-chart-host" id="v2d-chart-host"></div>
      </div>
    </div>
  `;

  function attach() {
    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);
    drawer.querySelector('#v2d-close').addEventListener('click', close);
    drawer.querySelectorAll('.v2-drawer-tab').forEach(el => {
      el.addEventListener('click', () => selectTab(el.dataset.pane));
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawer.classList.contains('open')) close();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }

  // ── Public API ────────────────────────────────────────────────────────
  window.V2 = window.V2 || {};
  window.V2.openDrawer = open;

  function open(ticker) {
    STATE.ticker = ticker;
    STATE.chartRendered = false;
    drawer.querySelector('#v2d-ticker').textContent = ticker;
    const entry = (window.V2.universe || []).find(u => u.ticker === ticker);
    drawer.querySelector('#v2d-name').textContent = entry?.name || '';
    drawer.querySelector('#v2d-price').textContent = '—';
    drawer.querySelector('#v2d-chg').textContent = '';
    drawer.querySelector('#v2d-meta').textContent = '';
    backdrop.classList.add('open');
    drawer.classList.add('open');
    selectTab(STATE.tab);
    loadHeaderPrice(ticker);
  }

  function close() {
    backdrop.classList.remove('open');
    drawer.classList.remove('open');
  }

  function selectTab(name) {
    STATE.tab = name;
    drawer.querySelectorAll('.v2-drawer-tab').forEach(t =>
      t.classList.toggle('active', t.dataset.pane === name));
    drawer.querySelectorAll('.v2-drawer-pane').forEach(p =>
      p.classList.toggle('active', p.dataset.pane === name));
    if (!STATE.ticker) return;
    if (name === 'tweets')    loadTweets(STATE.ticker);
    if (name === 'emails')    loadEmails(STATE.ticker);
    if (name === 'consensus') loadConsensus(STATE.ticker);
    if (name === 'chart')     loadChart(STATE.ticker);
  }

  // ── Header price ──────────────────────────────────────────────────────
  async function loadHeaderPrice(ticker) {
    try {
      const r = await fetch(`/api/prices?tickers=${encodeURIComponent(ticker)}`);
      if (!r.ok) return;
      const data = await r.json();
      const info = (data.prices || {})[ticker];
      if (!info) return;
      drawer.querySelector('#v2d-price').textContent = info.price.toFixed(2);
      const chg = drawer.querySelector('#v2d-chg');
      if (info.chg_pct != null) {
        const sign = info.chg_pct > 0 ? '+' : '';
        chg.textContent = `${sign}${info.chg_pct.toFixed(2)}%`;
        chg.className = `chg ${info.chg_pct >= 0 ? 'up' : 'down'}`;
      }
      drawer.querySelector('#v2d-meta').textContent = `via ${info.source}`;
    } catch (e) { /* ignore */ }
  }

  // ── Tweets pane ───────────────────────────────────────────────────────
  async function loadTweets(ticker) {
    const pane = drawer.querySelector('#v2d-pane-tweets');
    pane.innerHTML = '<div class="v2-drawer-loading">Loading tweets…</div>';
    try {
      const r = await fetch(`/api/tweets?ticker=${encodeURIComponent(ticker)}&hours=72&limit=40`);
      if (r.status === 503) {
        pane.innerHTML = '<div class="v2-drawer-disabled">Twitter corpus DB not available on this host. Requires local backend.</div>';
        return;
      }
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      if (!data.tweets?.length) {
        pane.innerHTML = `<div class="v2-drawer-empty">No tweets in last 72h mentioning ${ticker}.<br><small>Searched: ${(data.aliases||[]).join(', ')}</small></div>`;
        return;
      }
      pane.innerHTML = data.tweets.map(t => renderTweet(t)).join('');
    } catch (e) {
      pane.innerHTML = `<div class="v2-drawer-empty">Error loading tweets: ${e.message}</div>`;
    }
  }

  function renderTweet(t) {
    const handleLink = t.url
      ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">@${esc(t.handle)}</a>`
      : `@${esc(t.handle)}`;
    return `<div class="v2-tweet-card">
      <div>
        <span class="handle">${handleLink}</span>
        ${t.author ? `<span class="author">${esc(t.author)}</span>` : ''}
        ${t.category ? `<span class="cat-pill">${esc(t.category)}</span>` : ''}
        <span class="ts">${fmtTs(t.ts)}</span>
      </div>
      <div class="text">${esc(t.text)}</div>
      <div class="engage">
        ❤ ${t.likes||0} · 🔁 ${t.retweets||0} · 💬 ${t.replies||0}
        ${t.views ? ` · 👁 ${fmtCount(t.views)}` : ''}
        ${t.is_quote ? ' · (quote tweet)' : ''}
      </div>
    </div>`;
  }

  // ── Emails pane ───────────────────────────────────────────────────────
  async function loadEmails(ticker) {
    const pane = drawer.querySelector('#v2d-pane-emails');
    pane.innerHTML = '<div class="v2-drawer-loading">Loading emails (cache may need refresh — first call can take 10–30s)…</div>';
    try {
      const r = await fetch(`/api/emails?ticker=${encodeURIComponent(ticker)}&days=7&limit=40`);
      if (r.status === 503) {
        pane.innerHTML = '<div class="v2-drawer-disabled">Outlook integration unavailable on this host. Requires the local backend on a Windows machine with Outlook configured.</div>';
        return;
      }
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      if (!data.emails?.length) {
        pane.innerHTML = `<div class="v2-drawer-empty">No emails in last 7 days mentioning ${ticker}.<br><small>Searched: ${(data.aliases||[]).join(', ')}</small></div>`;
        return;
      }
      pane.innerHTML = data.emails.map(e => renderEmail(e)).join('');
    } catch (e) {
      pane.innerHTML = `<div class="v2-drawer-empty">Error loading emails: ${e.message}</div>`;
    }
  }

  function renderEmail(e) {
    const date = (e.date || '').replace('T', ' ').slice(0, 16);
    return `<div class="v2-email-card">
      <div>
        <span class="from">${esc(e.sender || e.sender_email || '?')}</span>
        <span class="date">${esc(date)}</span>
      </div>
      <div class="subj">${esc(e.subject || '(no subject)')}</div>
      <div class="snip">${esc(e.body_preview || e.body || '')}</div>
    </div>`;
  }

  // ── Consensus pane ────────────────────────────────────────────────────
  async function loadConsensus(ticker) {
    const pane = drawer.querySelector('#v2d-pane-consensus');
    pane.innerHTML = '<div class="v2-drawer-loading">Loading consensus…</div>';
    try {
      const r = await fetch(`/api/consensus?ticker=${encodeURIComponent(ticker)}`);
      if (r.status === 503) {
        pane.innerHTML = '<div class="v2-drawer-disabled">BBG consensus unavailable (no LAN connection and no cached snapshot for this ticker).</div>';
        return;
      }
      if (r.status === 404) {
        pane.innerHTML = `<div class="v2-drawer-empty">${ticker} is not in the consensus universe.</div>`;
        return;
      }
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      pane.innerHTML = renderConsensus(data);
    } catch (e) {
      pane.innerHTML = `<div class="v2-drawer-empty">Error loading consensus: ${e.message}</div>`;
    }
  }

  function renderConsensus(data) {
    const f = data.fields || {};
    const cards = [
      ['BEST_EPS',          'EPS (FY)'],
      ['BEST_SALES',        'Revenue'],
      ['BEST_EBITDA',       'EBITDA'],
      ['BEST_TARGET_PRICE', 'Target price'],
      ['BEST_ANALYST_RATING','Rating'],
      ['PE_RATIO',          'P/E'],
    ];
    const grid = cards.map(([k, label]) => {
      const v = f[k.toLowerCase()];
      const display = (v == null) ? '—'
        : (Math.abs(v) > 1000 ? v.toFixed(0)
           : Math.abs(v) > 10 ? v.toFixed(2)
           : v.toFixed(2));
      return `<div class="v2-cons-stat"><div class="label">${label}</div><div class="value">${display}</div></div>`;
    }).join('');

    let brokers = '';
    if (data.brokers?.length) {
      const cols = Object.keys(data.brokers[0]).slice(0, 5);
      brokers = `<h4 style="margin:14px 0 8px;color:var(--text2);font-size:.8rem">Broker grid (${data.brokers.length})</h4>
        <div class="v2-cons-brokers"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${data.brokers.slice(0, 20).map(b =>
          `<tr>${cols.map(c => `<td>${esc(String(b[c] ?? ''))}</td>`).join('')}</tr>`
        ).join('')}</tbody></table></div>`;
    }
    const src = data.source === 'bbg-live' ? `live · ${data.updated_at}` : `snapshot · ${data.updated_at || '?'}`;
    return `<div style="color:var(--text3);font-size:.7rem;margin-bottom:10px">Source: ${esc(src)}</div>
      <div class="v2-cons-grid">${grid}</div>${brokers}`;
  }

  // ── Chart pane ────────────────────────────────────────────────────────
  async function loadChart(ticker) {
    if (STATE.chartRendered) return;
    const host = drawer.querySelector('#v2d-chart-host');
    host.innerHTML = '<div class="v2-drawer-loading">Loading chart…</div>';
    try {
      const r = await fetch(`/api/chart?ticker=${encodeURIComponent(ticker)}&range=3mo&interval=1d`);
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      if (!data.timestamps?.length) {
        host.innerHTML = '<div class="v2-drawer-empty">No chart data.</div>';
        return;
      }
      host.innerHTML = '';
      const dates = data.timestamps.map(t => new Date(t * 1000));
      const trace = {
        x: dates, y: data.close, type: 'scatter', mode: 'lines',
        line: { color: '#58a6ff', width: 2 },
        fill: 'tozeroy', fillcolor: 'rgba(88,166,255,0.08)',
      };
      const layout = {
        paper_bgcolor: '#161b22', plot_bgcolor: '#161b22',
        font: { color: '#e6edf3', size: 11, family: 'inherit' },
        xaxis: { gridcolor: '#21262d', linecolor: '#30363d', tickfont: { size: 10 } },
        yaxis: { gridcolor: '#21262d', linecolor: '#30363d', tickfont: { size: 10 } },
        margin: { t: 10, r: 10, b: 30, l: 50 },
      };
      const config = { displayModeBar: false, responsive: true };
      // eslint-disable-next-line no-undef
      Plotly.newPlot(host, [trace], layout, config);
      STATE.chartRendered = true;
    } catch (e) {
      host.innerHTML = `<div class="v2-drawer-empty">Error loading chart: ${e.message}</div>`;
    }
  }

  // ── Utils ─────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  }
  function fmtTs(s) {
    if (!s) return '';
    const d = new Date(s.replace(' ', 'T') + (s.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d)) return s.slice(0, 16);
    const now = new Date();
    const diffMin = (now - d) / 60000;
    if (diffMin < 60)    return `${Math.round(diffMin)}m`;
    if (diffMin < 1440)  return `${Math.round(diffMin/60)}h`;
    return d.toISOString().slice(5, 16).replace('T', ' ');
  }
  function fmtCount(n) {
    if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
    if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
    return String(n);
  }
})();
