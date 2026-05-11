/* ════════════════════════════════════════════════════════════════════════
 * "+ Add Ticker" modal — POSTs a new entry to /api/tickers,
 * which appends to config/tickers.yaml and reloads the in-memory universe.
 * Triggered by window.V2.openAddTicker() (wired from dashboard-extensions.js).
 * ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  const backdrop = document.createElement('div');
  backdrop.className = 'v2-modal-backdrop';
  backdrop.innerHTML = `
    <div class="v2-modal" role="dialog" aria-modal="true">
      <h3>Add Ticker<span style="font-size:.7rem;font-weight:400;color:var(--text3)">writes to config/tickers.yaml</span></h3>
      <label>Ticker symbol</label>
      <input id="v2-add-ticker" placeholder="e.g. ARM" autocomplete="off">
      <label>Company name</label>
      <input id="v2-add-name" placeholder="e.g. Arm Holdings">
      <label>Sector</label>
      <input id="v2-add-sector" placeholder="e.g. Semis / CPU IP">
      <label>Bloomberg ticker <span style="color:var(--text3);font-weight:400">(optional — defaults to "&lt;ticker&gt; US Equity")</span></label>
      <input id="v2-add-bbg" placeholder="e.g. ARM US Equity">
      <label>Email search aliases <span style="color:var(--text3);font-weight:400">(comma-separated)</span></label>
      <input id="v2-add-email-aliases" placeholder="e.g. Arm Holdings, ARM Ltd">
      <label>Tweet search aliases <span style="color:var(--text3);font-weight:400">(comma-separated)</span></label>
      <input id="v2-add-tweet-aliases" placeholder="e.g. $ARM, Arm Holdings">
      <div class="v2-modal-err" id="v2-add-err"></div>
      <div class="v2-modal-actions">
        <button class="cancel" id="v2-add-cancel">Cancel</button>
        <button class="save"   id="v2-add-save">Save</button>
      </div>
    </div>
  `;

  function attach() {
    document.body.appendChild(backdrop);
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });
    document.getElementById('v2-add-cancel').addEventListener('click', close);
    document.getElementById('v2-add-save').addEventListener('click', save);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && backdrop.classList.contains('open')) close();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }

  window.V2 = window.V2 || {};
  window.V2.openAddTicker = open;

  function open() {
    backdrop.classList.add('open');
    document.getElementById('v2-add-err').textContent = '';
    ['v2-add-ticker','v2-add-name','v2-add-sector','v2-add-bbg',
     'v2-add-email-aliases','v2-add-tweet-aliases']
      .forEach(id => document.getElementById(id).value = '');
    setTimeout(() => document.getElementById('v2-add-ticker').focus(), 60);
  }

  function close() {
    backdrop.classList.remove('open');
  }

  async function save() {
    const err = document.getElementById('v2-add-err');
    const btn = document.getElementById('v2-add-save');
    err.textContent = '';
    const payload = {
      ticker: v('v2-add-ticker').toUpperCase(),
      name: v('v2-add-name') || undefined,
      sector: v('v2-add-sector') || undefined,
      bbg_ticker: v('v2-add-bbg') || undefined,
      search_aliases: {
        email: csv('v2-add-email-aliases'),
        tweet: csv('v2-add-tweet-aliases'),
      },
    };
    if (!payload.ticker) {
      err.textContent = 'Ticker symbol is required.';
      return;
    }
    btn.disabled = true;
    try {
      const r = await fetch('/api/tickers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        err.textContent = data.detail || `Save failed (HTTP ${r.status})`;
        return;
      }
      // Reload universe (also rebuilds the row-click ticker set)
      if (window.V2.loadUniverse) await window.V2.loadUniverse();
      if (window.V2.refreshPrices) window.V2.refreshPrices();
      close();
    } catch (e) {
      err.textContent = `Network error: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  function v(id) { return document.getElementById(id).value.trim(); }
  function csv(id) {
    return v(id).split(',').map(s => s.trim()).filter(Boolean);
  }
})();
