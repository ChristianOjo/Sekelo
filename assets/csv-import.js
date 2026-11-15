/* Sekelo — CSV price import
 * Depends on globals defined in admin.html at call time:
 *   products, entries, lastPrices, BRANCHES, BORDER, FLAG_THRESHOLD,
 *   activeBranch, renderBranch, buildRows, sbPost, refreshBadge, toast, esc, switchTab
 *
 * Expected columns (header names are case-insensitive, order doesn't matter):
 *   product_id | product      — one of the two (id wins if both present)
 *   price_zar (or price)      — number; "R 12,50" and "12.50" both work
 *   branch                    — optional; branch key or label. Falls back to the dropdown.
 *   available                 — optional; no/false/0/n → marked unavailable
 *   notes                     — optional
 */
(function () {
  const HEADER_ALIASES = {
    product_id: ['product_id', 'productid', 'id'],
    product: ['product', 'product_name', 'name', 'material'],
    price: ['price_zar', 'price', 'zar', 'amount'],
    branch: ['branch', 'store', 'location'],
    available: ['available', 'in_stock', 'stock'],
    notes: ['notes', 'note', 'row_notes', 'comment'],
  };

  let parsed = [];          // classified rows
  let fileName = '';
  let mounted = false;

  // ── CSV PARSING ─────────────────────────────────────────
  function detectDelimiter(text) {
    const first = text.split(/\r?\n/, 1)[0] || '';
    const counts = [',', ';', '\t'].map(d => [d, first.split(d).length - 1]);
    counts.sort((a, b) => b[1] - a[1]);
    return counts[0][1] > 0 ? counts[0][0] : ',';
  }

  function parseCSV(text) {
    text = text.replace(/^\uFEFF/, '');
    const delim = detectDelimiter(text);
    const rows = [];
    let row = [], field = '', inQ = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inQ) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; }
          else inQ = false;
        } else field += c;
      } else if (c === '"') inQ = true;
      else if (c === delim) { row.push(field); field = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(field); field = '';
        if (row.some(v => v.trim() !== '')) rows.push(row);
        row = [];
      } else field += c;
    }
    row.push(field);
    if (row.some(v => v.trim() !== '')) rows.push(row);
    return rows;
  }

  function mapHeaders(headerRow) {
    const norm = headerRow.map(h => h.trim().toLowerCase().replace(/[\s-]+/g, '_'));
    const map = {};
    for (const [key, aliases] of Object.entries(HEADER_ALIASES)) {
      const idx = norm.findIndex(h => aliases.includes(h));
      if (idx !== -1) map[key] = idx;
    }
    return map;
  }

  function parsePrice(raw) {
    if (raw == null) return NaN;
    let s = String(raw).replace(/[Rr\s\u00A0]/g, '');
    if (!s) return NaN;
    if (s.includes(',') && s.includes('.')) s = s.replace(/,/g, '');
    else if (s.includes(',')) s = s.replace(',', '.');
    const n = parseFloat(s);
    return isNaN(n) ? NaN : n;
  }

  function parseAvailable(raw) {
    if (raw == null || String(raw).trim() === '') return true;
    return !/^(no|n|false|0|unavailable|out)$/i.test(String(raw).trim());
  }

  // ── MATCHING ────────────────────────────────────────────
  function findBranch(raw, fallbackKey) {
    if (raw == null || !String(raw).trim()) return BRANCHES.find(b => b.key === fallbackKey);
    const v = String(raw).trim().toLowerCase();
    return BRANCHES.find(b => b.key.toLowerCase() === v || b.label.toLowerCase() === v);
  }

  const normName = v => String(v).toLowerCase().replace(/[×]/g, 'x').replace(/[^a-z0-9.]+/g, ' ').trim();

  function findProduct(idRaw, nameRaw) {
    if (idRaw != null && String(idRaw).trim() !== '') {
      const id = parseInt(idRaw, 10);
      const p = products.find(x => x.id === id);
      if (p) return p;
    }
    if (nameRaw != null && String(nameRaw).trim() !== '') {
      const n = normName(nameRaw);
      const exact = products.find(x => normName(x.product_name) === n);
      if (exact) return exact;
      // unique partial match either way (e.g. "Cement 32.5R" vs "Cement 32.5R 50kg")
      const partial = products.filter(x => {
        const pn = normName(x.product_name);
        return pn.includes(n) || n.includes(pn);
      });
      if (partial.length === 1) return partial[0];
    }
    return null;
  }

  function classify(rows, fallbackKey) {
    const map = mapHeaders(rows[0]);
    const problems = [];
    if (map.price === undefined) problems.push('No price column found (expected price_zar or price).');
    if (map.product_id === undefined && map.product === undefined)
      problems.push('No product column found (expected product_id or product).');
    if (problems.length) return { error: problems.join(' '), items: [] };

    const seen = new Map();
    const items = rows.slice(1).map((r, i) => {
      const get = k => (map[k] === undefined ? null : r[map[k]]);
      const item = { line: i + 2, status: 'ok', msg: '' };
      let branch = findBranch(get('branch'), fallbackKey);
      const rawBranch = get('branch');
      if (!branch && rawBranch != null && String(rawBranch).trim()) {
        branch = BRANCHES.find(b => b.key === fallbackKey);
        item.msg = `Branch “${String(rawBranch).trim()}” unknown, using default`;
        item.warn = true;
      }
      const prod = findProduct(get('product_id'), get('product'));
      const available = parseAvailable(get('available'));
      const price = parsePrice(get('price'));

      item.rawName = (get('product') || get('product_id') || '').toString().trim();
      item.branch = branch; item.prod = prod; item.available = available;
      item.price = price; item.notes = (get('notes') || '').toString().trim();

      if (!branch) { item.status = 'error'; item.msg = 'No branch'; }
      else if (!prod) { item.status = 'error'; item.msg = 'Product not found'; }
      else if (available && (isNaN(price) || price <= 0)) { item.status = 'error'; item.msg = 'Missing or invalid price'; }
      else {
        const key = `${branch.key}|${prod.id}`;
        if (seen.has(key)) { items[seen.get(key)].status = 'dupe'; items[seen.get(key)].msg = 'Overridden by later row'; }
        seen.set(key, i);
      }
      return item;
    });
    return { error: null, items };
  }

  // ── APPLY ───────────────────────────────────────────────
  function importable() {
    return parsed.filter(r => r.status === 'ok');
  }

  function applyToEntries() {
    const touched = new Set();
    importable().forEach(r => {
      const bk = r.branch.key;
      entries[bk][r.prod.id] = {
        price_zar: r.available ? String(r.price) : '',
        available: r.available,
        row_notes: r.notes || '',
      };
      touched.add(bk);
    });
    return touched;
  }

  function loadIntoForm() {
    const touched = applyToEntries();
    if (!touched.size) { toast('Nothing valid to import.', 'err'); return; }
    if (!touched.has(activeBranch)) activeBranch = [...touched][0];
    if (typeof renderBranchTabs === 'function') renderBranchTabs();
    renderBranch(activeBranch);
    toast(`✓ ${importable().length} rows loaded across ${touched.size} branch${touched.size !== 1 ? 'es' : ''}.\nReview on Price Entry, then submit.`, 'ok');
    switchTab('entry');
  }

  async function submitDirect() {
    const touched = [...applyToEntries()];
    if (!touched.length) { toast('Nothing valid to import.', 'err'); return; }
    const btn = document.getElementById('csvSubmit');
    btn.disabled = true; btn.textContent = 'Submitting…';
    try {
      const rows = touched.flatMap(bk => buildRows(bk, null, 'pending'));
      const res = await sbPost('price_submissions', rows);
      if (!res.ok) { toast('Submit failed — see console.', 'err'); console.error(await res.text()); return; }
      touched.forEach(bk => { entries[bk] = {}; });
      renderBranch(activeBranch);
      await refreshBadge();
      toast(`✓ ${rows.length} prices submitted for review.`, 'ok');
      reset();
      switchTab('review');
    } catch (e) {
      toast('Network error.', 'err'); console.error(e);
    } finally {
      btn.disabled = false; btn.textContent = 'Submit for Review';
    }
  }

  // ── TEMPLATE DOWNLOAD ───────────────────────────────────
  function downloadTemplate() {
    const bk = document.getElementById('csvBranch')?.value || activeBranch;
    const q = v => `"${String(v).replace(/"/g, '""')}"`;
    const lines = ['product_id,product,branch,price_zar,available,notes'];
    products.forEach(p => lines.push([p.id, q(p.product_name), bk, '', 'yes', ''].join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `sekelo-price-template-${bk}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── UI ──────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('csvImportStyles')) return;
    const s = document.createElement('style');
    s.id = 'csvImportStyles';
    s.textContent = `
      .csv-box{background:var(--surface);border:1px solid var(--border);padding:24px;margin-bottom:14px;}
      .csv-title{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:1.5px;color:var(--accent);margin-bottom:6px;}
      .csv-help{font-family:var(--mono);font-size:9px;color:var(--text-3);line-height:1.8;margin-bottom:18px;}
      .csv-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;}
      .csv-drop{flex:1;min-width:240px;border:1px dashed var(--border-2);padding:22px;text-align:center;cursor:pointer;transition:all .2s;font-size:11px;color:var(--text-2);}
      .csv-drop:hover,.csv-drop.over{border-color:var(--accent);background:var(--accent-bg);color:var(--accent);}
      .csv-drop small{display:block;font-family:var(--mono);font-size:9px;color:var(--text-3);margin-top:6px;}
      .csv-sel{background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:11px;padding:10px 12px;outline:none;}
      .csv-sel:focus{border-color:var(--accent);}
      .csv-lbl{font-family:var(--mono);font-size:9px;color:var(--text-3);display:block;margin-bottom:5px;}
      .csv-sum{font-family:var(--mono);font-size:10px;color:var(--text-2);margin-bottom:12px;}
      .csv-sum b{color:var(--text);font-weight:500;}
      .csv-err{color:var(--up);}.csv-warn{color:var(--flag);}.csv-ok{color:var(--down);}
      .csv-scroll{max-height:420px;overflow:auto;border:1px solid var(--border);}
      .csv-actions{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;}
    `;
    document.head.appendChild(s);
  }

  function shell() {
    const opts = BRANCHES.map(b => `<option value="${esc(b.key)}" ${b.key === activeBranch ? 'selected' : ''}>${esc(b.label)}</option>`).join('');
    return `
      <div class="csv-box">
        <div class="csv-title">Import prices from CSV</div>
        <div class="csv-help">
          Columns: <b>product_id</b> or <b>product</b>, <b>price_zar</b>, optional <b>branch</b>, <b>available</b>, <b>notes</b>.<br>
          Rows without a branch column use the branch selected here. Nothing goes live until it is approved in the Review Queue.
        </div>
        <div class="csv-row">
          <div>
            <label class="csv-lbl" for="csvBranch">Default branch</label>
            <select class="csv-sel" id="csvBranch" onchange="CsvImport.reclassify()">${opts}</select>
          </div>
          <div class="csv-drop" id="csvDrop">
            Drop a .csv file here or click to choose
            <small id="csvFileName">No file selected</small>
          </div>
          <input type="file" id="csvFile" accept=".csv,text/csv" style="display:none">
          <button class="sbtn-outline" onclick="CsvImport.template()">Download template</button>
        </div>
      </div>
      <div id="csvPreview"></div>`;
  }

  let lastText = '';

  function handleText(text, name) {
    lastText = text;
    fileName = name;
    document.getElementById('csvFileName').textContent = name;
    reclassify();
  }

  function reclassify() {
    if (!lastText) return;
    const rows = parseCSV(lastText);
    const out = document.getElementById('csvPreview');
    if (rows.length < 2) {
      parsed = [];
      out.innerHTML = `<div class="csv-box csv-err" style="font-family:var(--mono);font-size:11px">File needs a header row and at least one data row.</div>`;
      return;
    }
    const fallback = document.getElementById('csvBranch').value;
    const res = classify(rows, fallback);
    if (res.error) {
      parsed = [];
      out.innerHTML = `<div class="csv-box csv-err" style="font-family:var(--mono);font-size:11px">${esc(res.error)}</div>`;
      return;
    }
    parsed = res.items;
    renderPreview();
  }

  function renderPreview() {
    const ok = parsed.filter(r => r.status === 'ok').length;
    const err = parsed.filter(r => r.status === 'error').length;
    const dupe = parsed.filter(r => r.status === 'dupe').length;
    const threshold = typeof FLAG_THRESHOLD !== 'undefined' ? FLAG_THRESHOLD : 15;

    const reasons = {};
    parsed.filter(r => r.status === 'error').forEach(r => { reasons[r.msg] = (reasons[r.msg] || 0) + 1; });
    const reasonTxt = Object.entries(reasons).map(([m, n]) => `${n}× ${esc(m)}`).join(' · ');

    const body = parsed.map(r => {
      const lp = r.prod && r.branch ? lastPrices[r.prod.id]?.[r.branch.key] : null;
      let change = '<span class="diff new">New</span>';
      let flagged = false;
      if (lp && r.available && !isNaN(r.price)) {
        const l = parseFloat(lp.price_zar);
        if (l > 0) {
          const pct = (r.price - l) / l * 100;
          flagged = Math.abs(pct) > threshold;
          change = Math.abs(pct) < 0.1
            ? '<span class="diff flat">flat</span>'
            : `<span class="diff ${flagged ? 'flag' : pct > 0 ? 'up' : 'down'}">${pct > 0 ? '↑' : '↓'} ${Math.abs(pct).toFixed(1)}%${flagged ? '<span class="flag-icon">⚑</span>' : ''}</span>`;
        }
      }
      const state = r.status === 'ok'
        ? (r.warn ? `<span class="csv-warn">${esc(r.msg)}</span>` : '<span class="csv-ok">Ready</span>')
        : r.status === 'dupe'
          ? `<span class="csv-warn">${esc(r.msg)}</span>`
          : `<span class="csv-err">${esc(r.msg)}</span>`;
      const priceCell = !r.available ? '<span style="color:var(--text-3)">unavailable</span>'
        : isNaN(r.price) ? '—' : `R ${r.price.toFixed(2)}`;
      return `<tr class="${flagged ? 'flagged' : ''}" ${r.status !== 'ok' ? 'style="opacity:.55"' : ''}>
        <td class="mono">${r.line}</td>
        <td class="name">${esc(r.prod ? r.prod.product_name : r.rawName || '—')}</td>
        <td>${esc(r.branch ? r.branch.label : '—')}</td>
        <td class="mono r">${priceCell}</td>
        <td class="mono r">${lp ? 'R ' + parseFloat(lp.price_zar).toFixed(2) : '—'}</td>
        <td class="r">${change}</td>
        <td>${state}</td>
      </tr>`;
    }).join('');

    document.getElementById('csvPreview').innerHTML = `
      <div class="csv-box">
        <div class="csv-sum">
          <b>${parsed.length}</b> rows · <b class="csv-ok">${ok}</b> ready
          ${err ? ` · <b class="csv-err">${err}</b> with errors (skipped)` : ''}
          ${reasonTxt ? `<div class="csv-err" style="margin-top:6px">${reasonTxt}</div>` : ''}
          ${dupe ? ` · <b class="csv-warn">${dupe}</b> duplicates (last row wins)` : ''}
        </div>
        <div class="csv-scroll">
          <table class="rtable" style="border:none">
            <thead><tr>
              <th>Line</th><th style="min-width:200px">Product</th><th>Branch</th>
              <th class="r">New price</th><th class="r">Last known</th><th class="r">Change</th><th>Status</th>
            </tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>
        <div class="csv-actions">
          <button class="sbtn" id="csvSubmit" onclick="CsvImport.submit()" ${ok ? '' : 'disabled'}>Submit for Review</button>
          <button class="sbtn-outline" onclick="CsvImport.load()" ${ok ? '' : 'disabled'}>Load into entry form</button>
          <button class="sbtn-outline" style="margin-left:auto" onclick="CsvImport.reset()">Clear</button>
        </div>
      </div>`;
  }

  function reset() {
    parsed = []; lastText = ''; fileName = '';
    const f = document.getElementById('csvFile'); if (f) f.value = '';
    const n = document.getElementById('csvFileName'); if (n) n.textContent = 'No file selected';
    const p = document.getElementById('csvPreview'); if (p) p.innerHTML = '';
  }

  function readFile(file) {
    if (!file) return;
    if (!/\.csv$/i.test(file.name) && file.type !== 'text/csv') {
      toast('Please choose a .csv file.', 'err'); return;
    }
    const fr = new FileReader();
    fr.onload = () => handleText(String(fr.result), file.name);
    fr.onerror = () => toast('Could not read file.', 'err');
    fr.readAsText(file);
  }

  function render() {
    injectStyles();
    const host = document.getElementById('importContent');
    if (!host) return;
    if (!mounted) {
      host.innerHTML = shell();
      const drop = document.getElementById('csvDrop');
      const input = document.getElementById('csvFile');
      drop.addEventListener('click', () => input.click());
      input.addEventListener('change', e => readFile(e.target.files[0]));
      ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
      ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
      drop.addEventListener('drop', e => readFile(e.dataTransfer.files[0]));
      mounted = true;
    }
  }

  window.CsvImport = {
    render, reset, reclassify,
    template: downloadTemplate,
    load: loadIntoForm,
    submit: submitDirect,
    // exposed for testing
    _parseCSV: parseCSV, _parsePrice: parsePrice,
  };
})();
