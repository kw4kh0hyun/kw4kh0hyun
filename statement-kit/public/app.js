// StatementKit UI — everything here runs locally; file contents never leave the browser.
import * as pdfjs from '/vendor/pdf.min.mjs';
import { extractPages } from '/lib/pdf-text.js';
import { parseStatement } from '/lib/parser.js';
import { exportTransactions, FORMATS } from '/lib/export.js';

pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdf.worker.min.mjs';

const FREE_PAGES = 3;
const FREE_EXPORTS_PER_DAY = 1;
const $ = (id) => document.getElementById(id);
const store = {
  get(k) {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch {}
  },
  del(k) {
    try {
      localStorage.removeItem(k);
    } catch {}
  },
};

const state = { files: [], rows: [], pro: false, config: null };

// ---------- license ----------
async function loadConfig() {
  try {
    state.config = await (await fetch('/api/config')).json();
  } catch {
    state.config = {};
  }
  if (state.config.price) $('price').textContent = state.config.price;
  if (state.config.passDays) $('pass-days').textContent = state.config.passDays;
  const buy = $('buy');
  if (state.config.checkoutUrl) buy.href = state.config.checkoutUrl;
  else {
    buy.removeAttribute('href');
    buy.classList.add('disabled');
    buy.textContent = 'Checkout not configured';
  }
}

async function verifyStoredKey() {
  const key = store.get('sk_license');
  if (!key) return setPro(false);
  try {
    const r = await (await fetch('/api/license/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) })).json();
    if (r.valid) return setPro(true, r.expires);
    if (r.reason === 'expired') $('key-msg').textContent = 'Your Pro pass has expired.';
    store.del('sk_license');
  } catch {
    // Offline: trust a previously verified key until its expiry.
    const exp = Number(store.get('sk_license_exp'));
    if (exp > Date.now()) return setPro(true, exp);
  }
  setPro(false);
}

function setPro(on, expires) {
  state.pro = on;
  $('pro-badge').hidden = !on;
  if (on && expires) {
    store.set('sk_license_exp', String(expires));
    $('key-msg').textContent = `Pro active until ${new Date(expires).toLocaleDateString()}.`;
  }
  fillFormats();
}

async function claimFromCheckout() {
  const sid = new URLSearchParams(location.search).get('session_id');
  if (!sid) return;
  history.replaceState(null, '', location.pathname + '#pricing');
  $('key-msg').textContent = 'Confirming your payment…';
  try {
    const r = await (await fetch(`/api/license/claim?session_id=${encodeURIComponent(sid)}`)).json();
    if (r.key) {
      store.set('sk_license', r.key);
      $('key-input').value = r.key;
      $('key-msg').textContent = 'Thanks! Pro is active. Save your key to use it on another device:';
      setPro(true, r.expires);
    } else $('key-msg').textContent = r.error || 'Could not confirm payment.';
  } catch {
    $('key-msg').textContent = 'Could not reach the server to confirm payment. Reload to retry.';
  }
}

$('key-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const key = $('key-input').value.trim();
  if (!key) return;
  store.set('sk_license', key);
  $('key-msg').textContent = 'Checking…';
  await verifyStoredKey();
  if (!state.pro) $('key-msg').textContent = 'That key is not valid.';
});

// ---------- file intake ----------
const drop = $('drop');
drop.addEventListener('click', () => $('file').click());
drop.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && $('file').click());
$('file').addEventListener('change', (e) => handleFiles([...e.target.files]));
for (const ev of ['dragenter', 'dragover']) drop.addEventListener(ev, (e) => (e.preventDefault(), drop.classList.add('over')));
for (const ev of ['dragleave', 'drop']) drop.addEventListener(ev, () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  handleFiles([...e.dataTransfer.files].filter((f) => /pdf$/i.test(f.type) || /\.pdf$/i.test(f.name)));
});
$('date-order').addEventListener('change', () => reparse());

function askPassword(name, retry) {
  return new Promise((resolve) => {
    const dlg = $('pw-dialog');
    $('pw-label').textContent = retry ? `Wrong password for ${name}. Try again:` : `${name} is password-protected.`;
    $('pw-input').value = '';
    dlg.returnValue = '';
    dlg.onclose = () => resolve(dlg.returnValue === 'ok' ? $('pw-input').value : null);
    dlg.showModal();
  });
}

async function loadPdf(file) {
  const data = new Uint8Array(await file.arrayBuffer());
  const task = pdfjs.getDocument({ data, isEvalSupported: false, verbosity: 0 });
  task.onPassword = async (update, reason) => {
    const pw = await askPassword(file.name, reason === pdfjs.PasswordResponses.INCORRECT_PASSWORD);
    if (pw === null) task.destroy();
    else update(pw);
  };
  return task.promise;
}

async function handleFiles(files) {
  if (!files.length) return;
  if (!state.pro && files.length > 1) {
    showStatus(`Batch conversion is a Pro feature — processing only “${files[0].name}”. <a href="#pricing">Get Pro</a> to merge many statements at once.`, 'warn');
    files = files.slice(0, 1);
  } else showStatus(`Reading ${files.length} file${files.length > 1 ? 's' : ''} locally…`);
  state.files = [];
  for (const f of files) {
    try {
      const pdf = await loadPdf(f);
      let pages = await extractPages(pdf);
      let truncated = false;
      if (!state.pro && pages.length > FREE_PAGES) {
        pages = pages.slice(0, FREE_PAGES);
        truncated = true;
      }
      state.files.push({ name: f.name, pages, truncated, totalPages: pdf.numPages });
      pdf.destroy();
    } catch (err) {
      state.files.push({ name: f.name, error: err?.name === 'PasswordException' ? 'Password required' : 'Could not open this PDF' });
    }
  }
  reparse();
}

function reparse() {
  const order = $('date-order').value;
  state.rows = [];
  const results = [];
  for (const f of state.files) {
    if (f.error) {
      results.push({ file: f, error: f.error });
      continue;
    }
    const r = parseStatement(f.pages, { dateOrder: order });
    results.push({ file: f, r });
    for (const t of r.transactions) state.rows.push({ ...t, file: f.name });
    if (order === 'auto' && r.dateOrder) $('date-order').dataset.detected = r.dateOrder;
  }
  if (state.files.length > 1) state.rows.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
  guessCurrency();
  render(results);
}

function guessCurrency() {
  const text = state.files.flatMap((f) => f.pages || []).flatMap((p) => p.items.map((i) => i.str)).join(' ');
  const cur = /£|\bGBP\b|sort code/i.test(text) ? 'GBP' : /€|\bEUR\b|IBAN/i.test(text) ? 'EUR' : /\bCAD\b/.test(text) ? 'CAD' : /\bAUD\b|\bBSB\b/.test(text) ? 'AUD' : /\$/.test(text) ? 'USD' : null;
  if (cur) $('currency').value = cur;
}

// ---------- rendering ----------
const money = (n) => (n === null || n === undefined ? '' : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function showStatus(html, kind = 'info') {
  const s = $('status');
  s.hidden = false;
  s.className = `status ${kind}`;
  s.innerHTML = html;
}

function render(results) {
  const notes = [];
  for (const { file, r, error } of results) {
    if (error) notes.push(`<b>${esc(file.name)}</b>: ${esc(error)}`);
    else {
      for (const w of r.warnings) notes.push(`<b>${esc(file.name)}</b>: ${esc(w)}`);
      if (file.truncated) notes.push(`<b>${esc(file.name)}</b>: free plan reads the first ${FREE_PAGES} of ${file.totalPages} pages. <a href="#pricing">Get Pro</a> for the full statement.`);
    }
  }
  if (notes.length) showStatus(notes.join('<br>'), 'warn');
  else $('status').hidden = true;

  if (!state.rows.length) {
    $('results').hidden = true;
    return;
  }
  $('results').hidden = false;

  // Verification banner
  const checks = results.filter((x) => x.r && x.r.transactions.length).map((x) => x.r.check);
  const bad = checks.filter((c) => c.status === 'mismatch');
  const unverified = checks.filter((c) => c.status === 'unverified');
  const v = $('verify');
  if (bad.length) {
    v.className = 'verify warn';
    v.innerHTML = `<b>Needs review</b><span>${esc(bad.map((c) => c.message).join(' '))}</span>`;
  } else if (unverified.length) {
    v.className = 'verify neutral';
    v.innerHTML = `<b>Not verifiable</b><span>${esc(unverified[0].message)}</span>`;
  } else {
    v.className = 'verify ok';
    const n = checks.reduce((s, c) => s + (c.checked || 0), 0);
    v.innerHTML = `<b>✓ Balances verified</b><span>${n} running balance${n === 1 ? '' : 's'} matched${checks.length > 1 ? ` across ${checks.length} statements` : ''}${checks.some((c) => /closing/.test(c.message)) ? ', closing balance confirmed' : ''}.</span>`;
  }

  const inflow = state.rows.reduce((s, t) => s + (t.amount > 0 ? t.amount : 0), 0);
  const outflow = state.rows.reduce((s, t) => s + (t.amount < 0 ? -t.amount : 0), 0);
  const dates = state.rows.map((t) => t.date).filter(Boolean).sort();
  $('stats').innerHTML = [
    ['Transactions', state.rows.length],
    ['Money in', money(inflow)],
    ['Money out', money(outflow)],
    ['Period', dates.length ? `${dates[0]} → ${dates.at(-1)}` : '—'],
  ].map(([k, val]) => `<div><span>${k}</span><b>${val}</b></div>`).join('');

  const multi = state.files.length > 1;
  $('table').classList.toggle('multi', multi);
  $('table').querySelector('tbody').innerHTML = state.rows
    .map((t, i) => `<tr data-i="${i}" class="${t.flag ? 'flag' : ''}" title="${t.flag === 'balance-mismatch' ? 'Does not match the running balance' : t.flag === 'sign-guessed' ? 'Debit/credit sign was guessed' : ''}">
      <td>${esc(t.date || '?')}</td>
      <td contenteditable="true" data-f="description" spellcheck="false">${esc(t.description)}</td>
      <td class="num ${t.amount < 0 ? 'neg' : 'pos'}" contenteditable="true" data-f="amount">${money(t.amount)}</td>
      <td class="num">${money(t.balance)}</td>
      <td class="file-col">${esc(t.file)}</td></tr>`)
    .join('');
}

$('table').addEventListener('blur', (e) => {
  const td = e.target.closest('td[data-f]');
  if (!td) return;
  const row = state.rows[Number(td.parentElement.dataset.i)];
  if (td.dataset.f === 'description') row.description = td.textContent.trim();
  else {
    const n = Number(td.textContent.replace(/[^0-9.\-]/g, ''));
    if (Number.isFinite(n)) {
      row.amount = Math.round(n * 100) / 100;
      td.className = `num ${row.amount < 0 ? 'neg' : 'pos'}`;
    }
    td.textContent = money(row.amount);
  }
}, true);

// ---------- export ----------
function fillFormats() {
  const sel = $('format');
  const cur = sel.value;
  sel.innerHTML = Object.entries(FORMATS)
    .map(([k, f]) => `<option value="${k}">${f.label}${f.pro && !state.pro ? ' — Pro' : ''}</option>`)
    .join('');
  if (cur) sel.value = cur;
}

function canExport(format) {
  if (state.pro) return true;
  if (FORMATS[format].pro) {
    showStatus(`${FORMATS[format].label} export is part of Pro. <a href="#pricing">See pricing</a> — or choose plain CSV.`, 'warn');
    return false;
  }
  const today = new Date().toISOString().slice(0, 10);
  const used = store.get('sk_free_day') === today ? Number(store.get('sk_free_count')) || 0 : 0;
  const sig = state.files.map((f) => f.name).join('|');
  if (used >= FREE_EXPORTS_PER_DAY && store.get('sk_free_sig') !== sig) {
    showStatus(`The free plan exports ${FREE_EXPORTS_PER_DAY} statement per day. <a href="#pricing">Get Pro</a> for unlimited exports.`, 'warn');
    return false;
  }
  if (store.get('sk_free_sig') !== sig) {
    store.set('sk_free_day', today);
    store.set('sk_free_count', String(used + 1));
    store.set('sk_free_sig', sig);
  }
  return true;
}

$('download').addEventListener('click', () => {
  const format = $('format').value;
  if (!state.rows.length || !canExport(format)) return;
  const first = state.files.find((f) => !f.error);
  const out = exportTransactions(format, state.rows, { currency: $('currency').value, dateOrder: $('date-order').value === 'auto' ? $('date-order').dataset.detected : $('date-order').value });
  const blob = new Blob([out], { type: FORMATS[format].mime });
  const a = document.createElement('a');
  const base = state.files.length > 1 ? 'statements-merged' : (first?.name || 'statement').replace(/\.pdf$/i, '');
  a.href = URL.createObjectURL(blob);
  a.download = `${base}${format === 'quickbooks' ? '-quickbooks' : format === 'xero' ? '-xero' : ''}.${FORMATS[format].ext}`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

$('copy').addEventListener('click', async () => {
  if (!state.rows.length || !canExport('csv')) return;
  const tsv = ['Date\tDescription\tAmount\tBalance', ...state.rows.map((t) => [t.date, t.description, t.amount?.toFixed(2) ?? '', t.balance?.toFixed(2) ?? ''].join('\t'))].join('\n');
  try {
    await navigator.clipboard.writeText(tsv);
    $('copy').textContent = 'Copied ✓';
  } catch {
    $('copy').textContent = 'Copy failed';
  }
  setTimeout(() => ($('copy').textContent = 'Copy table'), 1500);
});

fillFormats();
await loadConfig();
await claimFromCheckout();
if (!state.pro) await verifyStoredKey();
