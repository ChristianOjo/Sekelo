/* Sekelo — shared client library.
 * Depends on assets/config.js (window.SB_URL, SB_KEY, BRANCHES, ...).
 * Everything is attached to `window` to avoid any redeclaration collisions
 * with inline page scripts.
 */
(function () {
  'use strict';

  /* ── Supabase REST helpers ─────────────────────────────── */
  function sbHeaders(extra) {
    var h = { apikey: window.SB_KEY, Authorization: 'Bearer ' + window.SB_KEY };
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }
  window.sbGet = async function (path) {
    var r = await fetch(window.SB_URL + '/rest/v1/' + path, { headers: sbHeaders() });
    if (!r.ok) throw new Error('Supabase ' + r.status + ' on ' + path.split('?')[0]);
    return r.json();
  };
  window.sbPost = async function (table, body) {
    var r = await fetch(window.SB_URL + '/rest/v1/' + table, {
      method: 'POST',
      headers: sbHeaders({ 'Content-Type': 'application/json', Prefer: 'return=representation' }),
      body: JSON.stringify(body)
    });
    if (!r.ok) throw new Error('Supabase POST ' + r.status);
    return r.json();
  };
  window.sbPatch = async function (path, body) {
    var r = await fetch(window.SB_URL + '/rest/v1/' + path, {
      method: 'PATCH',
      headers: sbHeaders({ 'Content-Type': 'application/json', Prefer: 'return=representation' }),
      body: JSON.stringify(body)
    });
    if (!r.ok) throw new Error('Supabase PATCH ' + r.status);
    return r.json();
  };

  /* ── Crypto ────────────────────────────────────────────── */
  window.sha256hex = async function (str) {
    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(function (b) {
      return b.toString(16).padStart(2, '0');
    }).join('');
  };

  /* ── Toast notifications (self-injecting) ──────────────── */
  var toastCssInjected = false;
  function injectToastCss() {
    if (toastCssInjected) return;
    toastCssInjected = true;
    var s = document.createElement('style');
    s.textContent =
      '.sekelo-toast{position:fixed;top:20px;right:20px;background:var(--surface,#131A24);' +
      'border:1px solid var(--border,#1E2C3C);padding:12px 18px;font-family:var(--mono,monospace);' +
      'font-size:10px;color:var(--text,#E8E2D5);z-index:9999;opacity:0;transform:translateY(-6px);' +
      'transition:all .3s;pointer-events:none;max-width:340px;line-height:1.6;}' +
      '.sekelo-toast.show{opacity:1;transform:translateY(0);}' +
      '.sekelo-toast.ok{border-color:var(--down,#3DAA6E);color:var(--down,#3DAA6E);}' +
      '.sekelo-toast.err{border-color:var(--up,#E05555);color:var(--up,#E05555);}' +
      '.sekelo-toast.info{border-color:var(--accent,#C8A55A);color:var(--accent,#C8A55A);}';
    document.head.appendChild(s);
  }
  window.toast = function (msg, type) {
    injectToastCss();
    var el = document.getElementById('sekelo-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sekelo-toast';
      el.className = 'sekelo-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = 'sekelo-toast show ' + (type || 'info');
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = 'sekelo-toast ' + (type || 'info'); }, 3200);
  };

  /* ── CSV export ────────────────────────────────────────── */
  window.exportCSV = function (filename, rows) {
    var esc = function (v) {
      if (v === null || v === undefined) return '';
      var s = String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    var csv = rows.map(function (r) { return r.map(esc).join(','); }).join('\n');
    var blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  };

  /* ── Formatting helpers ────────────────────────────────── */
  window.fmtZar = function (n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return 'R ' + Number(n).toLocaleString('en-ZA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  window.fmtSZL = function (n) {
    if (n === null || n === undefined || isNaN(n)) return '—';
    return 'E ' + Number(n).toLocaleString('en-ZA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  /* ── Theme persistence (runs automatically) ────────────── */
  function initTheme() {
    try {
      var t = localStorage.getItem('sekelo_theme');
      if (t) document.documentElement.setAttribute('data-theme', t);
      var btn = document.getElementById('themeBtn');
      if (btn) btn.textContent = (t === 'light') ? '☾' : '☀';
    } catch (e) { /* ignore */ }
  }
  // Pages may define their own toggleTheme; only define globally if absent.
  if (typeof window.toggleTheme !== 'function') {
    window.toggleTheme = function () {
      var cur = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = (cur === 'dark') ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('sekelo_theme', next); } catch (e) {}
      var btn = document.getElementById('themeBtn');
      if (btn) btn.textContent = (next === 'light') ? '☾' : '☀';
    };
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }

  /* ── SekeloGate — hash-aware access gate with rate limit ──
   * Replaces the old plaintext-compare gates.
   *   - Fetches the expected secret from app_config (key = opts.configKey).
   *   - If the stored value is a 64-char hex string, treats it as a SHA-256
   *     hash and hashes the user input before comparing (plaintext never
   *     leaves the server).
   *   - Otherwise falls back to plaintext compare (legacy) with a console
   *     warning, so existing deployments keep working until the row is
   *     migrated to a hash.
   *   - If the app_config row is missing and opts.fallbackHash is set, uses
   *     that hash (avoids lockout during migration; remove once row exists).
   *   - Brute-force rate limit: 5 failed attempts → 60 s lockout, stored
   *     per browser. (Server-side enforcement requires RLS/edge functions.)
   */
  var HASH_RE = /^[a-f0-9]{64}$/;
  var MAX_FAILS = 5;
  var LOCK_MS = 60 * 1000;

  function SekeloGate(opts) {
    this.configKey   = opts.configKey;
    this.storage     = opts.storage === 'session' ? sessionStorage : localStorage;
    this.storageKey  = opts.storageKey || 'sekelo_auth';
    this.onAuthed    = opts.onAuthed || function () {};
    this.fallbackHash = opts.fallbackHash || null;
    this.expected    = null;   // { value, mode: 'hash'|'plain'|'fallback' }
    this.lockKey     = 'sekelo_gate_fails_' + this.configKey;
    this._wire();
    this.init();
  }
  SekeloGate.prototype._el = function (id) { return document.getElementById(id); };
  SekeloGate.prototype._wire = function () {
    var self = this;
    // Inline handlers in markup call global auth(); bind it to this gate.
    window.auth = function () { self.check(); };
    var inp = this._el('passInput');
    if (inp) {
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); self.check(); }
      });
    }
    var btn = this._el('gateBtn');
    if (btn) btn.addEventListener('click', function () { self.check(); });
  };
  SekeloGate.prototype._lockState = function () {
    try { return JSON.parse(this.storage.getItem(this.lockKey)) || { fails: 0, until: 0 }; }
    catch (e) { return { fails: 0, until: 0 }; }
  };
  SekeloGate.prototype._saveLock = function (st) {
    try { this.storage.setItem(this.lockKey, JSON.stringify(st)); } catch (e) {}
  };
  SekeloGate.prototype.isLocked = function () {
    var st = this._lockState();
    if (st.until && Date.now() < st.until) return st.until - Date.now();
    if (st.until && Date.now() >= st.until) { this._saveLock({ fails: 0, until: 0 }); }
    return 0;
  };
  SekeloGate.prototype.recordFail = function () {
    var st = this._lockState();
    st.fails += 1;
    if (st.fails >= MAX_FAILS) { st.until = Date.now() + LOCK_MS; st.fails = 0; }
    this._saveLock(st);
    return st;
  };
  SekeloGate.prototype.loadExpected = async function () {
    if (this.expected) return this.expected;
    try {
      var rows = await window.sbGet('app_config?key=eq.' + encodeURIComponent(this.configKey) + '&select=value');
      if (rows && rows.length) {
        var v = rows[0].value;
        this.expected = { value: v, mode: HASH_RE.test(v) ? 'hash' : 'plain' };
        if (this.expected.mode === 'plain') {
          console.warn('[SekeloGate] ' + this.configKey + ' is stored in PLAINTEXT. Migrate to a SHA-256 hash — see README → Security.');
        }
        return this.expected;
      }
    } catch (e) {
      console.warn('[SekeloGate] could not load ' + this.configKey + ':', e.message);
    }
    if (this.fallbackHash) {
      this.expected = { value: this.fallbackHash, mode: 'fallback' };
      console.warn('[SekeloGate] ' + this.configKey + ' missing from app_config; using built-in fallback hash. Add the row to Supabase — see README.');
      return this.expected;
    }
    this.expected = null;
    return null;
  };
  SekeloGate.prototype.check = async function () {
    var btn = this._el('gateBtn'), err = this._el('gateErr'), inp = this._el('passInput');
    if (!inp || !btn || !err) return;
    var val = inp.value.trim();
    if (!val) return;

    var remain = this.isLocked();
    if (remain > 0) {
      err.textContent = 'Too many attempts. Try again in ' + Math.ceil(remain / 1000) + ' s.';
      return;
    }

    btn.disabled = true; btn.textContent = 'Checking…';
    var exp = await this.loadExpected();
    btn.disabled = false; btn.textContent = btn.dataset.label || btn.textContent;

    if (!exp) {
      err.textContent = 'Configuration error — please try again.';
      return;
    }

    var match;
    if (exp.mode === 'plain') {
      match = (val === exp.value);
    } else {
      match = ((await window.sha256hex(val)) === exp.value);
    }

    if (match) {
      this._saveLock({ fails: 0, until: 0 });
      try { this.storage.setItem(this.storageKey, '1'); } catch (e) {}
      var gate = this._el('gate'), app = this._el('app');
      if (gate) gate.style.display = 'none';
      if (app) app.style.display = 'block';
      err.textContent = '';
      this.onAuthed();
    } else {
      var st = this.recordFail();
      var left = MAX_FAILS - st.fails;
      if (st.until && Date.now() < st.until) {
        err.textContent = 'Too many failed attempts. Locked for 60 seconds.';
      } else {
        err.textContent = 'Incorrect access code. ' + left + ' attempt' + (left === 1 ? '' : 's') + ' left.';
      }
      inp.value = ''; inp.focus();
    }
  };
  SekeloGate.prototype.logout = function () {
    try { this.storage.removeItem(this.storageKey); } catch (e) {}
    var gate = this._el('gate'), app = this._el('app');
    if (gate) gate.style.display = 'flex';
    if (app) app.style.display = 'none';
    var inp = this._el('passInput'), err = this._el('gateErr');
    if (inp) inp.value = '';
    if (err) err.textContent = '';
  };
  SekeloGate.prototype.init = function () {
    var self = this;
    // Remember button label for restore
    var btn = this._el('gateBtn');
    if (btn) btn.dataset.label = btn.textContent;
    // Existing session?
    if (this.storage.getItem(this.storageKey) === '1') {
      var gate = this._el('gate'), app = this._el('app');
      if (gate) gate.style.display = 'none';
      if (app) app.style.display = 'block';
      this.onAuthed();
    } else {
      // Pre-load expected secret while user reads the gate
      this.loadExpected();
    }
  };

  window.SekeloGate = SekeloGate;
})();
