/* ════════════════════════════════════════════════════════════════════════
 * News tab — unified Tweets + Emails feed from local sources only.
 *
 * Hits /api/news/feed (one round trip) and renders two columns. Filters by
 * sector (dropdown) or ticker (dropdown populated from the response's ticker
 * frequency tally). Click any card to open the v2 drawer focused on the first
 * ticker tag.
 *
 * Hidden when the backend is unavailable (the tab button stays display:none).
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const STATE = {
    raw: null,
    loaded: false,
    activeTicker: '',
    activeSector: '',
  };

  function init() {
    // Wait for V2 backend probe to finish — poll briefly.
    let tries = 0;
    const tick = () => {
      tries++;
      const mode = window.V2?.state?.mode;
      if (mode === 'live' || mode === 'cached') {
        showTabButton();
        wireControls();
      } else if (mode === 'probing' && tries < 30) {
        setTimeout(tick, 200);
      }
      // offline → leave the tab hidden
    };
    tick();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function showTabButton() {
    const btn = document.getElementById('v2-news-tab');
    if (btn) btn.style.display = '';
  }

  function wireControls() {
    document.getElementById('v2-news-refresh').addEventListener('click', async () => {
      // Trigger an Outlook cache refresh (slow — 10-30s). Then reload the feed.
      const meta = document.getElementById('v2-news-meta');
      meta.textContent = 'Refreshing emails cache (10–30s)…';
      try {
        await fetch('/api/emails/refresh?days=7', { method: 'POST' });
      } catch (e) { /* ignore */ }
      await loadFeed();
    });

    document.getElementById('v2-news-sector').addEventListener('change', (ev) => {
      STATE.activeSector = ev.target.value;
      STATE.activeTicker = '';
      document.getElementById('v2-news-ticker').value = '';
      render();
    });

    document.getElementById('v2-news-ticker').addEventListener('change', (ev) => {
      STATE.activeTicker = ev.target.value;
      STATE.activeSector = '';
      document.getElementById('v2-news-sector').value = '';
      render();
    });

    // Lazy-load: only fetch when the tab is first opened.
    const tabBtn = document.getElementById('v2-news-tab');
    tabBtn?.addEventListener('click', () => {
      if (!STATE.loaded) loadFeed();
    });
  }

  async function loadFeed() {
    const tweetsHost = document.getElementById('v2-news-tweets');
    const emailsHost = document.getElementById('v2-news-emails');
    tweetsHost.innerHTML = '<div class="v2-drawer-loading">Loading tweets…</div>';
    emailsHost.innerHTML = '<div class="v2-drawer-loading">Loading emails…</div>';
    try {
      const r = await fetch('/api/news/feed?hours=48&tweet_limit=120&email_limit=120');
      if (!r.ok) throw new Error(r.status);
      STATE.raw = await r.json();
      STATE.loaded = true;
      populateDropdowns();
      render();
    } catch (e) {
      tweetsHost.innerHTML = `<div class="v2-drawer-empty">Erro: ${e.message}</div>`;
      emailsHost.innerHTML = `<div class="v2-drawer-empty">Erro: ${e.message}</div>`;
    }
  }

  function populateDropdowns() {
    if (!STATE.raw) return;
    const secSel = document.getElementById('v2-news-sector');
    const tckSel = document.getElementById('v2-news-ticker');

    // Sector list — only sectors that have at least one matched item.
    const universe = window.V2?.universe || [];
    const byTicker = Object.fromEntries(universe.map(u => [u.ticker, u]));
    const sectorsInUse = new Set();
    Object.keys(STATE.raw.ticker_counts || {}).forEach(t => {
      const u = byTicker[t];
      if (u?.sector) sectorsInUse.add(u.sector);
    });
    secSel.innerHTML = '<option value="">Setor: todos</option>' +
      [...sectorsInUse].sort().map(s => `<option value="${escAttr(s)}">${escHtml(s)}</option>`).join('');

    // Ticker dropdown — ordered by mention frequency.
    tckSel.innerHTML = '<option value="">Ticker: todos</option>' +
      Object.entries(STATE.raw.ticker_counts || {})
        .map(([t, n]) => `<option value="${escAttr(t)}">${escHtml(t)} (${n})</option>`)
        .join('');
  }

  function render() {
    if (!STATE.raw) return;
    const universe = window.V2?.universe || [];
    const byTicker = Object.fromEntries(universe.map(u => [u.ticker, u]));

    let tweets = STATE.raw.tweets;
    let emails = STATE.raw.emails;

    if (STATE.activeTicker) {
      tweets = tweets.filter(t => t.tickers.includes(STATE.activeTicker));
      emails = emails.filter(e => e.tickers.includes(STATE.activeTicker));
    } else if (STATE.activeSector) {
      const sl = STATE.activeSector.toLowerCase();
      const inSector = new Set(
        universe.filter(u => (u.sector || '').toLowerCase().includes(sl)).map(u => u.ticker)
      );
      tweets = tweets.filter(t => t.tickers.some(x => inSector.has(x)));
      emails = emails.filter(e => e.tickers.some(x => inSector.has(x)));
    }

    document.getElementById('v2-news-tweet-count').textContent = tweets.length;
    document.getElementById('v2-news-email-count').textContent = emails.length;
    document.getElementById('v2-news-meta').textContent =
      `${STATE.raw.tweet_count} tweets · ${STATE.raw.email_count} emails (last 48h)`;

    const tweetsHost = document.getElementById('v2-news-tweets');
    const emailsHost = document.getElementById('v2-news-emails');
    tweetsHost.innerHTML = tweets.length
      ? tweets.map(t => renderTweetCard(t)).join('')
      : '<div class="v2-drawer-empty">No matching tweets.</div>';
    emailsHost.innerHTML = emails.length
      ? emails.map(e => renderEmailCard(e)).join('')
      : (STATE.raw.emails_cache_present
          ? '<div class="v2-drawer-empty">No matching emails.</div>'
          : '<div class="v2-drawer-disabled">Email cache empty. Click ↻ Refresh (10–30s) to pull recent emails from Outlook.</div>');

    // Click → open drawer focused on first ticker tag
    document.querySelectorAll('[data-news-tickers]').forEach(el => {
      el.addEventListener('click', (ev) => {
        if (ev.target.closest('a')) return;
        const t = el.getAttribute('data-news-tickers').split(',')[0];
        if (t && window.V2?.openDrawer) window.V2.openDrawer(t);
      });
    });
  }

  function renderTweetCard(t) {
    const link = t.url
      ? `<a href="${escAttr(t.url)}" target="_blank" rel="noopener">@${escHtml(t.handle)}</a>`
      : `@${escHtml(t.handle)}`;
    return `<div class="v2-tweet-card v2-news-card" data-news-tickers="${escAttr(t.tickers.join(','))}">
      <div>
        <span class="handle">${link}</span>
        ${t.author ? `<span class="author">${escHtml(t.author)}</span>` : ''}
        ${t.category ? `<span class="cat-pill">${escHtml(t.category)}</span>` : ''}
        <span class="ts">${fmtTs(t.ts)}</span>
      </div>
      <div class="text">${escHtml(t.text)}</div>
      <div class="v2-news-tags">
        ${t.tickers.map(x => `<span class="v2-news-tag">${escHtml(x)}</span>`).join('')}
        <span class="engage">❤ ${t.likes||0} · 🔁 ${t.retweets||0}${t.views?` · 👁 ${fmtCount(t.views)}`:''}</span>
      </div>
    </div>`;
  }

  function renderEmailCard(e) {
    const date = (e.ts || '').replace('T', ' ').slice(0, 16);
    return `<div class="v2-email-card v2-news-card" data-news-tickers="${escAttr(e.tickers.join(','))}">
      <div>
        <span class="from">${escHtml(e.sender || e.sender_email || '?')}</span>
        <span class="date">${escHtml(date)}</span>
      </div>
      <div class="subj">${escHtml(e.subject || '(no subject)')}</div>
      <div class="snip">${escHtml(e.preview || '')}</div>
      <div class="v2-news-tags">
        ${e.tickers.map(x => `<span class="v2-news-tag">${escHtml(x)}</span>`).join('')}
        ${e.folder ? `<span class="engage">${escHtml(e.folder)}</span>` : ''}
      </div>
    </div>`;
  }

  // ── Utils ─────────────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  }
  function escAttr(s) { return escHtml(s); }
  function fmtTs(s) {
    if (!s) return '';
    const d = new Date((s.includes('T') ? s : s.replace(' ', 'T')) + (s.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d)) return s.slice(0, 16);
    const diffMin = (Date.now() - d) / 60000;
    if (diffMin < 60)   return `${Math.round(diffMin)}m`;
    if (diffMin < 1440) return `${Math.round(diffMin/60)}h`;
    return d.toISOString().slice(5, 16).replace('T', ' ');
  }
  function fmtCount(n) {
    if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
    if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
    return String(n);
  }
})();
