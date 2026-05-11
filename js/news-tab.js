/* ════════════════════════════════════════════════════════════════════════
 * News & Social — browse view over our local Twitter corpus + email cache.
 *
 * No external APIs. All data comes from:
 *   - C:/Users/felipe.monteiro/.claude/data/twitter-briefing/tweets.sqlite (10k+ rows, FTS5)
 *   - backend/data/emails_cache.json (populated by /api/emails/refresh)
 *
 * Layout:
 *   [Mode toggle: Tweets | Emails] [Search box] [↻ Refresh emails]
 *   ┌──────────────┬──────────────────────────────────┐
 *   │ Sidebar      │ Status line + result list        │
 *   │  Lookback    │  card · card · card · …          │
 *   │  Category    │                                  │
 *   │  Handle      │  [Prev]  [Next]  showing X–Y     │
 *   └──────────────┴──────────────────────────────────┘
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const STATE = {
    mode: 'tweets',                // 'tweets' | 'emails'
    q: '',
    hours: 48,                     // tweet lookback
    days: 7,                       // email lookback (derived from hours)
    category: null,
    handle: null,
    sender: null,
    folder: null,
    offset: 0,
    limit: 50,
    meta: null,                    // /api/repo/meta payload (cached after first load)
    inflight: 0,
  };

  // ── Boot ──────────────────────────────────────────────────────────────
  function init() {
    let tries = 0;
    const tick = () => {
      tries++;
      const mode = window.V2?.state?.mode;
      if (mode === 'live' || mode === 'cached') {
        document.getElementById('v2-news-tab').style.display = '';
        wire();
        loadMetaAndQuery();
      } else if (mode === 'probing' && tries < 30) {
        setTimeout(tick, 200);
      }
    };
    tick();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Wiring ────────────────────────────────────────────────────────────
  function wire() {
    // Mode toggle
    document.querySelectorAll('.v2-repo-mode').forEach(btn => {
      btn.addEventListener('click', () => switchMode(btn.dataset.mode));
    });

    // Search (debounced)
    let qTimer;
    document.getElementById('v2-repo-q').addEventListener('input', (ev) => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => {
        STATE.q = ev.target.value.trim();
        STATE.offset = 0;
        query();
      }, 250);
    });

    // Lookback pills
    document.querySelectorAll('#v2-repo-lookback .v2-repo-side-pill').forEach(b => {
      b.addEventListener('click', () => {
        document.querySelectorAll('#v2-repo-lookback .v2-repo-side-pill')
          .forEach(p => p.classList.toggle('active', p === b));
        STATE.hours = Number(b.dataset.h);
        STATE.days = Math.max(1, Math.min(60, Math.ceil(STATE.hours / 24)));
        STATE.offset = 0;
        query();
      });
    });

    // Refresh emails
    document.getElementById('v2-repo-refresh-emails').addEventListener('click', async () => {
      const btn = document.getElementById('v2-repo-refresh-emails');
      btn.disabled = true; btn.textContent = '⏳ Refreshing…';
      try {
        await fetch(`/api/emails/refresh?days=${STATE.days}`, { method: 'POST' });
        await loadMeta();
        if (STATE.mode === 'emails') await query();
      } catch (e) {
        // ignore
      } finally {
        btn.disabled = false; btn.textContent = '↻ Refresh emails';
      }
    });
  }

  // ── Meta + first query ────────────────────────────────────────────────
  async function loadMetaAndQuery() {
    await loadMeta();
    await query();
  }

  async function loadMeta() {
    try {
      const r = await fetch('/api/repo/meta');
      if (!r.ok) throw new Error(r.status);
      STATE.meta = await r.json();
      renderSidebar();
      renderModeTotals();
    } catch (e) {
      console.warn('[news-tab] meta load failed', e);
    }
  }

  function renderModeTotals() {
    const tw = STATE.meta?.tweets;
    const em = STATE.meta?.emails;
    document.getElementById('v2-repo-tw-total').textContent = tw ? ` · ${fmtCount(tw.total)}` : '';
    document.getElementById('v2-repo-em-total').textContent = em ? ` · ${fmtCount(em.total)}` : '';
  }

  function renderSidebar() {
    const meta = STATE.meta || {};

    // Categories (tweets)
    const catsHost = document.getElementById('v2-repo-cats');
    const cats = (meta.tweets?.categories) || {};
    catsHost.innerHTML = renderSidebarRow('— all —', null, sumValues(cats), STATE.category == null, 'category') +
      Object.entries(cats)
        .map(([c, n]) => renderSidebarRow(c, c, n, STATE.category === c, 'category'))
        .join('');

    // Handles (tweets)
    const handlesHost = document.getElementById('v2-repo-handles');
    const handles = meta.tweets?.top_handles || [];
    handlesHost.innerHTML = renderSidebarRow('— all —', null, '', STATE.handle == null, 'handle') +
      handles.map(h => renderSidebarRow('@' + h.handle, h.handle, h.n, STATE.handle === h.handle, 'handle')).join('');

    // Senders (emails)
    const sendersHost = document.getElementById('v2-repo-senders');
    const senders = meta.emails?.top_senders || [];
    sendersHost.innerHTML = renderSidebarRow('— all —', null, '', STATE.sender == null, 'sender') +
      senders.map(s => renderSidebarRow(s.sender, s.sender, s.n, STATE.sender === s.sender, 'sender')).join('');

    // Folders (emails)
    const foldersHost = document.getElementById('v2-repo-folders');
    const folders = meta.emails?.folders || {};
    foldersHost.innerHTML = renderSidebarRow('— all —', null, '', STATE.folder == null, 'folder') +
      Object.entries(folders)
        .map(([f, n]) => renderSidebarRow(f || '(none)', f, n, STATE.folder === f, 'folder'))
        .join('');

    // Click handlers — delegated
    document.querySelectorAll('.v2-repo-side-row').forEach(el => {
      el.addEventListener('click', () => {
        const kind = el.dataset.kind;
        const val = el.dataset.val || null;
        STATE[kind] = val === '__NULL__' ? null : val;
        STATE.offset = 0;
        renderSidebar(); // re-render to update active class
        query();
      });
    });
  }

  function renderSidebarRow(label, val, count, active, kind) {
    const cls = 'v2-repo-side-row' + (active ? ' active' : '');
    const v = val === null ? '__NULL__' : escAttr(val);
    return `<div class="${cls}" data-kind="${kind}" data-val="${v}">
      <span class="lbl">${escHtml(label)}</span>
      ${count !== '' ? `<span class="cnt">${fmtCount(count)}</span>` : ''}
    </div>`;
  }

  // ── Mode switch ───────────────────────────────────────────────────────
  function switchMode(mode) {
    if (STATE.mode === mode) return;
    STATE.mode = mode;
    STATE.offset = 0;
    document.querySelectorAll('.v2-repo-mode')
      .forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    document.querySelectorAll('.v2-repo-side-section[data-only]').forEach(s => {
      s.style.display = (s.dataset.only === mode) ? '' : 'none';
    });
    query();
  }

  // ── Query ─────────────────────────────────────────────────────────────
  async function query() {
    const seq = ++STATE.inflight;
    setStatus('Loading…');
    const url = STATE.mode === 'tweets' ? buildTweetUrl() : buildEmailUrl();
    try {
      const r = await fetch(url);
      if (seq !== STATE.inflight) return;     // a newer query has fired
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      render(data);
    } catch (e) {
      setStatus(`Error: ${e.message}`);
      document.getElementById('v2-repo-list').innerHTML = '';
      document.getElementById('v2-repo-pager').innerHTML = '';
    }
  }

  function buildTweetUrl() {
    const p = new URLSearchParams();
    if (STATE.q) p.set('q', STATE.q);
    p.set('hours', STATE.hours);
    if (STATE.category) p.set('category', STATE.category);
    if (STATE.handle) p.set('handle', STATE.handle);
    p.set('offset', STATE.offset);
    p.set('limit', STATE.limit);
    return '/api/repo/tweets?' + p.toString();
  }

  function buildEmailUrl() {
    const p = new URLSearchParams();
    if (STATE.q) p.set('q', STATE.q);
    p.set('days', STATE.days);
    if (STATE.sender) p.set('sender', STATE.sender);
    if (STATE.folder) p.set('folder', STATE.folder);
    p.set('offset', STATE.offset);
    p.set('limit', STATE.limit);
    return '/api/repo/emails?' + p.toString();
  }

  // ── Render ────────────────────────────────────────────────────────────
  function render(data) {
    const total = data.total || 0;
    const from = total === 0 ? 0 : STATE.offset + 1;
    const to = STATE.offset + (data.count || 0);
    const filters = describeFilters();
    setStatus(total === 0
      ? `No results${filters ? ' · ' + filters : ''}`
      : `Showing ${from}–${to} of ${fmtCount(total)}${filters ? ' · ' + filters : ''}`);

    const host = document.getElementById('v2-repo-list');
    if (STATE.mode === 'tweets') {
      host.innerHTML = (data.tweets || []).map(renderTweet).join('')
        || '<div class="v2-drawer-empty">Nothing matches your filters.</div>';
    } else {
      if (!data.cache_present) {
        host.innerHTML = '<div class="v2-drawer-disabled">Email cache is empty. Click <b>↻ Refresh emails</b> above (takes 10–30s — scans Outlook MAPI).</div>';
      } else {
        host.innerHTML = (data.emails || []).map(renderEmail).join('')
          || '<div class="v2-drawer-empty">Nothing matches your filters.</div>';
      }
    }
    renderPager(total);

    // Click → drawer for first ticker tag
    host.querySelectorAll('[data-news-tickers]').forEach(el => {
      el.addEventListener('click', (ev) => {
        if (ev.target.closest('a')) return;
        const t = el.getAttribute('data-news-tickers').split(',')[0];
        if (t && window.V2?.openDrawer) window.V2.openDrawer(t);
      });
    });
  }

  function describeFilters() {
    const bits = [];
    if (STATE.mode === 'tweets') {
      if (STATE.category) bits.push(`cat=${STATE.category}`);
      if (STATE.handle) bits.push(`@${STATE.handle}`);
      bits.push(lookbackLabel(STATE.hours));
    } else {
      if (STATE.sender) bits.push(STATE.sender.split(' ')[0]);
      if (STATE.folder) bits.push(STATE.folder);
      bits.push(`${STATE.days}d`);
    }
    if (STATE.q) bits.push(`"${STATE.q}"`);
    return bits.join(' · ');
  }

  function lookbackLabel(h) {
    if (h <= 24) return '24h';
    if (h <= 48) return '48h';
    if (h <= 168) return '7d';
    if (h <= 720) return '30d';
    return '1y';
  }

  function setStatus(s) {
    document.getElementById('v2-repo-status').textContent = s;
  }

  function renderPager(total) {
    const pager = document.getElementById('v2-repo-pager');
    if (total <= STATE.limit) { pager.innerHTML = ''; return; }
    const page = Math.floor(STATE.offset / STATE.limit) + 1;
    const pages = Math.ceil(total / STATE.limit);
    pager.innerHTML = `
      <button id="v2-repo-prev" ${STATE.offset === 0 ? 'disabled' : ''}>← Prev</button>
      <span>Page ${page} / ${pages}</span>
      <button id="v2-repo-next" ${STATE.offset + STATE.limit >= total ? 'disabled' : ''}>Next →</button>
    `;
    pager.querySelector('#v2-repo-prev')?.addEventListener('click', () => {
      STATE.offset = Math.max(0, STATE.offset - STATE.limit); query();
    });
    pager.querySelector('#v2-repo-next')?.addEventListener('click', () => {
      STATE.offset += STATE.limit; query();
    });
  }

  // ── Card renderers ────────────────────────────────────────────────────
  function renderTweet(t) {
    const link = t.url
      ? `<a href="${escAttr(t.url)}" target="_blank" rel="noopener">@${escHtml(t.handle)}</a>`
      : `@${escHtml(t.handle)}`;
    const tags = (t.tickers || []).map(x => `<span class="v2-news-tag">${escHtml(x)}</span>`).join('');
    return `<div class="v2-tweet-card v2-news-card" ${t.tickers?.length ? `data-news-tickers="${escAttr(t.tickers.join(','))}"` : ''}>
      <div>
        <span class="handle">${link}</span>
        ${t.author ? `<span class="author">${escHtml(t.author)}</span>` : ''}
        ${t.category ? `<span class="cat-pill">${escHtml(t.category)}</span>` : ''}
        <span class="ts">${fmtTs(t.ts)}</span>
      </div>
      <div class="text">${linkify(escHtml(t.text))}</div>
      <div class="v2-news-tags">
        ${tags}
        <span class="engage">❤ ${t.likes||0} · 🔁 ${t.retweets||0}${t.views?` · 👁 ${fmtCount(t.views)}`:''}</span>
      </div>
    </div>`;
  }

  function renderEmail(e) {
    const date = (e.ts || '').replace('T', ' ').slice(0, 16);
    const tags = (e.tickers || []).map(x => `<span class="v2-news-tag">${escHtml(x)}</span>`).join('');
    return `<div class="v2-email-card v2-news-card" ${e.tickers?.length ? `data-news-tickers="${escAttr(e.tickers.join(','))}"` : ''}>
      <div>
        <span class="from">${escHtml(e.sender || e.sender_email || '?')}</span>
        <span class="date">${escHtml(date)}</span>
      </div>
      <div class="subj">${escHtml(e.subject || '(no subject)')}</div>
      <div class="snip">${escHtml(e.preview || '')}</div>
      <div class="v2-news-tags">
        ${tags}
        ${e.folder ? `<span class="engage">${escHtml(e.folder)}</span>` : ''}
      </div>
    </div>`;
  }

  // ── Utils ─────────────────────────────────────────────────────────────
  function sumValues(obj) {
    return Object.values(obj || {}).reduce((a, b) => a + (b || 0), 0);
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
    if (n == null || n === '') return '';
    if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
    if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
    return String(n);
  }
})();
