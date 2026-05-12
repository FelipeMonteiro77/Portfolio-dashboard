/* ════════════════════════════════════════════════════════════════════════
 * News & Social — ranked inbox
 *
 *   ┌───────────── Toolbar: lookback pills + meta + ↻ Refresh ─────────┐
 *   │ Ribbon: TOP TICKERS HOJE   TOP THEMES HOJE                       │
 *   ├─────────────────────────────┬────────────────────────────────────┤
 *   │ TWEETS (ranked)             │ EMAILS (ranked)                    │
 *   │  ▸ @handle · tickers · ts   │  ▸ sender · subj · tickers · date  │
 *   │  text…                      │  preview…                          │
 *   │  ▸ next                     │  ▸ next                            │
 *   └─────────────────────────────┴────────────────────────────────────┘
 *
 * Click a ticker pill (ribbon) → filters BOTH columns to that ticker only.
 * Click a card → opens the v2 drawer focused on its first ticker tag.
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const STATE = {
    hours: 48,
    activeTicker: null,
    data: null,
    inflight: 0,
  };

  // Reveal the tab as soon as we know the backend is reachable. Prefer the
  // V2 mode pill if dashboard-extensions has already probed, otherwise do our
  // own /api/health probe so the tab never depends on another module booting
  // successfully.
  async function init() {
    console.info('[news-tab] init');
    let revealed = false;
    const reveal = () => {
      if (revealed) return;
      revealed = true;
      const tabBtn = document.getElementById('v2-news-tab');
      if (tabBtn) tabBtn.style.display = '';
      wire();
      load();
    };

    // Fast path: V2 already probed.
    const mode = window.V2?.state?.mode;
    if (mode === 'live' || mode === 'cached') { reveal(); return; }

    // Poll V2 for up to 6s (covers the dashboard-extensions startup race).
    for (let i = 0; i < 30 && !revealed; i++) {
      await sleep(200);
      const m = window.V2?.state?.mode;
      if (m === 'live' || m === 'cached') { reveal(); return; }
      if (m === 'offline') break;   // V2 says backend is down — no point waiting
    }

    // Fallback: probe /api/health ourselves. If it answers, reveal anyway.
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      if (r.ok) {
        console.info('[news-tab] revealing via fallback probe');
        reveal();
        return;
      }
    } catch (e) {
      console.info('[news-tab] backend unreachable, tab stays hidden', e);
    }
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function wire() {
    document.querySelectorAll('#v2-inbox-lookback .v2-repo-side-pill').forEach(b => {
      b.addEventListener('click', () => {
        document.querySelectorAll('#v2-inbox-lookback .v2-repo-side-pill')
          .forEach(p => p.classList.toggle('active', p === b));
        STATE.hours = Number(b.dataset.h);
        load();
      });
    });

    document.getElementById('v2-inbox-refresh').addEventListener('click', async () => {
      const btn = document.getElementById('v2-inbox-refresh');
      btn.disabled = true; btn.textContent = '⏳ Refreshing…';
      try {
        const r = await fetch(`/api/emails/refresh?days=${Math.max(1, Math.ceil(STATE.hours/24))}`, { method: 'POST' });
        if (!r.ok) {
          // Surface the backend error message inline (most common: Outlook closed).
          let msg = `HTTP ${r.status}`;
          try { const d = await r.json(); msg = d.detail || msg; } catch (_) {}
          alert(`Email refresh failed:\n\n${msg}`);
        }
      } catch (e) {
        alert(`Email refresh failed: ${e.message}`);
      }
      await load();
      btn.disabled = false; btn.textContent = '↻ Refresh';
    });
  }

  async function load() {
    const seq = ++STATE.inflight;
    setStatus('Loading…');
    try {
      const r = await fetch(`/api/repo/feed?hours=${STATE.hours}&tweet_limit=60&email_limit=60`);
      if (seq !== STATE.inflight) return;
      if (!r.ok) throw new Error(r.status);
      STATE.data = await r.json();
      render();
    } catch (e) {
      setStatus(`Error: ${e.message}`);
    }
  }

  function setStatus(s) {
    document.getElementById('v2-inbox-meta').textContent = s;
  }

  function render() {
    if (!STATE.data) return;
    const d = STATE.data;

    // Meta line
    const filterNote = STATE.activeTicker
      ? ` · filtered to ${STATE.activeTicker} (click again to clear)`
      : '';
    setStatus(
      `${fmtCount(d.tweet_pool)} tweets · ${fmtCount(d.email_pool)} emails ranked from last ${lookbackLabel(d.hours)}${filterNote}`
    );

    // Top tickers ribbon
    const tickersHost = document.getElementById('v2-inbox-top-tickers');
    if (!d.top_tickers?.length) {
      tickersHost.innerHTML = '<span class="v2-inbox-dim">— no universe mentions yet —</span>';
    } else {
      tickersHost.innerHTML = d.top_tickers.map(t => {
        const active = STATE.activeTicker === t.ticker ? ' active' : '';
        return `<button class="v2-inbox-ticker-chip${active}" data-ticker="${escAttr(t.ticker)}">
          ${escHtml(t.ticker)}<span class="n">${t.n}</span>
        </button>`;
      }).join('');
      tickersHost.querySelectorAll('.v2-inbox-ticker-chip').forEach(el => {
        el.addEventListener('click', () => {
          const t = el.dataset.ticker;
          STATE.activeTicker = (STATE.activeTicker === t) ? null : t;
          render();
        });
      });
    }

    // Top themes ribbon
    const themesHost = document.getElementById('v2-inbox-top-themes');
    if (!d.top_themes?.length) {
      themesHost.innerHTML = '<span class="v2-inbox-dim">— no themes —</span>';
    } else {
      themesHost.innerHTML = d.top_themes
        .map(t => `<span class="v2-inbox-theme-chip">${escHtml(t.theme)}<span class="n">${t.n}</span></span>`)
        .join('');
    }

    // Filter by active ticker if set
    const tweets = STATE.activeTicker
      ? d.tweets.filter(t => t.tickers.includes(STATE.activeTicker))
      : d.tweets;
    const emails = STATE.activeTicker
      ? d.emails.filter(e => e.tickers.includes(STATE.activeTicker))
      : d.emails;

    document.getElementById('v2-inbox-tw-count').textContent = `${tweets.length}`;
    document.getElementById('v2-inbox-em-count').textContent = `${emails.length}`;

    const tweetsHost = document.getElementById('v2-inbox-tweets');
    tweetsHost.innerHTML = tweets.length
      ? tweets.map(renderTweet).join('')
      : '<div class="v2-drawer-empty">No tweets match this filter.</div>';

    const emailsHost = document.getElementById('v2-inbox-emails');
    if (!d.emails_cache_present) {
      emailsHost.innerHTML = '<div class="v2-drawer-disabled">Email cache empty. Click <b>↻ Refresh</b> above to scan Outlook (this now fetches full bodies — 30–90s first time).</div>';
    } else {
      emailsHost.innerHTML = emails.length
        ? emails.map(e => renderEmail(e, STATE.activeTicker)).join('')
        : '<div class="v2-drawer-empty">No emails match this filter.</div>';
    }

    // Wire card → drawer
    document.querySelectorAll('[data-news-tickers]').forEach(el => {
      el.addEventListener('click', (ev) => {
        if (ev.target.closest('a, .v2-news-tag, .v2-inbox-ticker-chip')) return;
        const t = el.getAttribute('data-news-tickers').split(',')[0];
        if (t && window.V2?.openDrawer) window.V2.openDrawer(t);
      });
    });
    // Clickable ticker tags on cards → set filter
    document.querySelectorAll('.v2-news-tag[data-set-ticker]').forEach(el => {
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        STATE.activeTicker = el.dataset.setTicker;
        render();
        document.querySelector('#tab-news')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  // ── Card renderers ────────────────────────────────────────────────────
  function renderTweet(t) {
    const handleLink = t.url
      ? `<a href="${escAttr(t.url)}" target="_blank" rel="noopener">@${escHtml(t.handle)}</a>`
      : `@${escHtml(t.handle)}`;
    const tags = (t.tickers || [])
      .map(x => `<span class="v2-news-tag" data-set-ticker="${escAttr(x)}">${escHtml(x)}</span>`)
      .join('');
    const tierBadge = t.is_tier1 ? '<span class="v2-inbox-tier1">★</span>' : '';
    return `<div class="v2-tweet-card v2-news-card" ${t.tickers?.length ? `data-news-tickers="${escAttr(t.tickers.join(','))}"` : ''}>
      <div>
        ${tierBadge}<span class="handle">${handleLink}</span>
        ${t.author ? `<span class="author">${escHtml(t.author)}</span>` : ''}
        ${t.category ? `<span class="cat-pill">${escHtml(t.category)}</span>` : ''}
        <span class="ts">${fmtTs(t.ts)}</span>
      </div>
      <div class="text">${linkify(escHtml(t.text))}</div>
      <div class="v2-news-tags">
        ${tags}
        <span class="engage">❤ ${t.likes||0} · 🔁 ${t.retweets||0}${t.views ? ` · 👁 ${fmtCount(t.views)}` : ''} · ▸ ${t.score}</span>
      </div>
    </div>`;
  }

  function renderEmail(e, activeTicker) {
    const date = (e.ts || '').replace('T', ' ').slice(0, 16);
    const tags = (e.tickers || [])
      .map(x => `<span class="v2-news-tag" data-set-ticker="${escAttr(x)}">${escHtml(x)}</span>`)
      .join('');
    // When a ticker chip is active, prefer the body snippet around that
    // ticker's mention so the user sees the actual relevant text.
    const snippet = (activeTicker && e.ticker_snippets && e.ticker_snippets[activeTicker])
      ? e.ticker_snippets[activeTicker]
      : (e.preview || '');
    const snippetCls = (activeTicker && e.ticker_snippets && e.ticker_snippets[activeTicker])
      ? 'snip snip-hit' : 'snip';
    const highlighted = activeTicker
      ? highlightTerm(escHtml(snippet), activeTicker)
      : escHtml(snippet);
    return `<div class="v2-email-card v2-news-card" ${e.tickers?.length ? `data-news-tickers="${escAttr(e.tickers.join(','))}"` : ''}>
      <div>
        <span class="from">${escHtml(e.sender || e.sender_email || '?')}</span>
        <span class="date">${escHtml(date)}</span>
      </div>
      <div class="subj">${escHtml(e.subject || '(no subject)')}</div>
      <div class="${snippetCls}">${highlighted}</div>
      <div class="v2-news-tags">
        ${tags}
        <span class="engage">${e.folder ? escHtml(e.folder) + ' · ' : ''}▸ ${e.score}</span>
      </div>
    </div>`;
  }

  function highlightTerm(escapedText, term) {
    if (!term) return escapedText;
    const safe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return escapedText.replace(new RegExp(safe, 'gi'), m => `<mark>${m}</mark>`);
  }

  // ── Utils ─────────────────────────────────────────────────────────────
  function lookbackLabel(h) {
    if (h <= 24) return '24h';
    if (h <= 48) return '48h';
    if (h <= 168) return '7d';
    if (h <= 720) return '30d';
    return '1y';
  }
  function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  }
  function escAttr(s) { return escHtml(s); }
  function linkify(s) {
    return s.replace(/https?:\/\/\S+/g,
      url => `<a href="${url}" target="_blank" rel="noopener">${url.length > 50 ? url.slice(0, 50) + '…' : url}</a>`);
  }
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
    if (n == null) return '';
    if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
    if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
    return String(n);
  }
})();
