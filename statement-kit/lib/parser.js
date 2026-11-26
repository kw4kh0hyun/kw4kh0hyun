// StatementKit parser — turns positioned PDF text into bank transactions.
// Pure ES module with no dependencies: runs in the browser and in Node tests.
//
// Input: pages = [{ items: [{ str, x, y, w, h }] }]   (y grows downward, PDF units)
// Output: { transactions, openingBalance, closingBalance, check, dateOrder, warnings }

const MONTHS = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5, jun: 6, june: 6,
  jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9, oct: 10, october: 10,
  nov: 11, november: 11, dec: 12, december: 12,
};
const MON = '(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)';

// Order matters: most specific first. Each returns {a, b, y} or {d, m, y} parts.
const DATE_PATTERNS = [
  { re: /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/, parse: (m) => ({ y: +m[1], m: +m[2], d: +m[3] }) },
  { re: /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?![\d])/, parse: (m) => ({ a: +m[1], b: +m[2], y: yr(m[3]) }) },
  { re: new RegExp(`^(\\d{1,2})(?:st|nd|rd|th)?[\\s\\-/.]*${MON}\\.?[\\s\\-/.,]*(\\d{4}|\\d{2}(?![\\d:.,]))?`, 'i'), parse: (m) => ({ d: +m[1], m: MONTHS[m[2].toLowerCase()], y: m[3] ? yr(m[3]) : null }) },
  { re: new RegExp(`^${MON}\\.?[\\s\\-/.]*(\\d{1,2})(?:st|nd|rd|th)?(?![\\d])(?:,?\\s*(\\d{4}))?`, 'i'), parse: (m) => ({ m: MONTHS[m[1].toLowerCase()], d: +m[2], y: m[3] ? +m[3] : null }) },
  { re: /^(\d{1,2})[/.-](\d{1,2})(?![\d/.-])/, parse: (m) => ({ a: +m[1], b: +m[2], y: null }) },
];
function yr(s) {
  const n = +s;
  return s.length === 2 ? 2000 + n : n;
}

/** Try to read a date at the start of `text`. Returns {parts, length} or null. */
export function matchDate(text) {
  const t = text.trim();
  for (const p of DATE_PATTERNS) {
    const m = t.match(p.re);
    if (m) {
      const parts = p.parse(m);
      if (parts.m !== undefined && (parts.m < 1 || parts.m > 12)) continue;
      if (parts.d !== undefined && (parts.d < 1 || parts.d > 31)) continue;
      if (parts.a !== undefined && (parts.a < 1 || parts.a > 31 || parts.b < 1 || parts.b > 31)) continue;
      if (parts.a !== undefined && parts.a > 12 && parts.b > 12) continue;
      if (parts.y !== null && parts.y !== undefined && (parts.y < 1990 || parts.y > 2100)) continue;
      return { parts, length: m[0].trimEnd().length };
    }
  }
  return null;
}

// Money: 1,234.56  1.234,56  -12.00  (12.00)  12.00-  12.00 CR  £12.00  $1,000.00 DR
const MONEY_RE = /^([-−–+]?)\s*\(?\s*([-−–]?)\s*[$£€¥₩]?\s*([-−–]?)(\d{1,3}(?:[,.\s']\d{3})*|\d+)([.,]\d{2})\s*\)?\s*([-−–])?\s*(CR|DR|Cr|Dr|C|D)?\.?$/;

/** Parse a money cell. Returns {value, explicitSign} or null. explicitSign: -1, 1 or 0 (unsigned). */
export function parseMoney(raw) {
  const s = raw.replace(/ /g, ' ').trim();
  const m = s.match(MONEY_RE);
  if (!m) return null;
  const intPart = m[4].replace(/[,.\s']/g, '');
  const dec = m[5].slice(1);
  let value = Number(`${intPart}.${dec}`);
  let sign = 0;
  if (m[1] && m[1] !== '+') sign = -1;
  if (m[1] === '+') sign = 1;
  if (m[2] || m[3] || m[6]) sign = -1;
  if (/^\(.*\)$/.test(s.replace(/\s*(CR|DR|Cr|Dr)\.?$/, ''))) sign = -1;
  if (m[7]) sign = /^c/i.test(m[7]) ? 1 : -1;
  return { value, explicitSign: sign };
}

const round2 = (n) => Math.round(n * 100) / 100;

// ---------- layout: items → lines → cells ----------

/** Group text items into visual lines, then merge close items into cells. */
export function buildLines(items) {
  const sorted = items.filter((i) => i.str && i.str.trim()).sort((a, b) => a.y - b.y || a.x - b.x);
  const lines = [];
  for (const it of sorted) {
    const h = it.h || 8;
    const line = lines.find((l) => Math.abs(l.y - it.y) <= Math.max(2, Math.min(l.h, h) * 0.45));
    if (line) {
      line.items.push(it);
      line.h = Math.max(line.h, h);
    } else lines.push({ y: it.y, h, items: [it] });
  }
  for (const l of lines) {
    l.items.sort((a, b) => a.x - b.x);
    const cells = [];
    for (const it of l.items) {
      const prev = cells[cells.length - 1];
      const gap = prev ? it.x - (prev.x + prev.w) : Infinity;
      const h = it.h || l.h;
      if (prev && gap < h * 0.9) {
        prev.str += gap > h * 0.15 ? ` ${it.str}` : it.str;
        prev.w = it.x + it.w - prev.x;
      } else cells.push({ str: it.str, x: it.x, w: it.w });
    }
    for (const c of cells) c.str = c.str.replace(/\s+/g, ' ').trim();
    l.cells = cells.filter((c) => c.str);
    l.text = l.cells.map((c) => c.str).join(' ');
  }
  return lines.sort((a, b) => a.y - b.y);
}

// ---------- column header detection ----------

const HEADER_WORDS = {
  debit: /^(debits?|withdrawals?|paid\s*out|money\s*out|payments?|out|dr|charges?|debit\s*amount|withdrawals?\s*\(-\)|amount\s*out|spent)$/i,
  credit: /^(credits?|deposits?|paid\s*in|money\s*in|receipts?|in|cr|credit\s*amount|deposits?\s*\(\+\)|amount\s*in|received)$/i,
  amount: /^(amount|transaction\s*amount|amount\s*\(.*\))$/i,
  balance: /^(balance|running\s*balance|balance\s*\(.*\)|closing\s*balance|ledger\s*balance)$/i,
  date: /^(date|posting\s*date|trans(action)?\s*date|value\s*date|posted|post\s*date)$/i,
  description: /^(description|details|transaction(\s*details)?|narrative|particulars|memo|payee|reference)$/i,
};

function detectHeader(line) {
  const cols = {};
  let hits = 0;
  for (const c of line.cells) {
    const label = c.str.replace(/[£$€:]/g, '').replace(/\(.*?\)/g, '').trim();
    for (const [k, re] of Object.entries(HEADER_WORDS)) {
      if (re.test(label) || re.test(c.str.trim())) {
        if (!cols[k]) {
          cols[k] = { left: c.x, right: c.x + c.w, center: c.x + c.w / 2 };
          hits++;
        }
        break;
      }
    }
  }
  const numeric = ['debit', 'credit', 'amount', 'balance'].filter((k) => cols[k]).length;
  return hits >= 2 && numeric >= 1 && (cols.date || cols.description) ? cols : null;
}

// ---------- summary lines ----------

const OPENING_RE = /(opening|beginning|starting|previous|start)\s*balance|balance\s*(brought|b\/?f)\s*forward|brought\s*forward|balance\s*forward|^b\/?f\b/i;
const CLOSING_RE = /(closing|ending|end|new|final)\s*balance|balance\s*carried\s*forward|carried\s*forward|^c\/?f\b/i;
const SKIP_RE = /^(page\s*\d|continued|total|totals|sub-?total|statement\s*(period|date)|account\s*(number|summary)|sort\s*code|iban|bic|swift)\b/i;

// ---------- main ----------

/**
 * @param {{items: object[]}[]} pages
 * @param {{dateOrder?: 'auto'|'DMY'|'MDY', year?: number}} opts
 */
export function parseStatement(pages, opts = {}) {
  const warnings = [];
  const allLines = pages.map((p, pi) => buildLines(p.items).map((l) => ({ ...l, page: pi + 1 })));
  const fullText = allLines.flat().map((l) => l.text).join('\n');

  const charCount = pages.reduce((n, p) => n + p.items.reduce((m, i) => m + (i.str || '').trim().length, 0), 0);
  if (charCount < 20) {
    return empty(['This PDF has no text layer (it is probably a scan or photo). StatementKit reads digital statements downloaded from online banking; OCR is not supported yet.']);
  }

  const yearHint = opts.year || guessYear(fullText);
  const raw = [];
  let header = null;
  let openingBalance = null;
  let closingBalance = null;
  let lastRow = null;

  for (const lines of allLines) {
    let pageHeader = null;
    for (const line of lines) {
      const h = detectHeader(line);
      if (h) {
        pageHeader = h;
        header = h;
        lastRow = null;
        continue;
      }
      const cols = pageHeader || header;
      const text = line.text;

      // Find a leading date (in the first or second cell — some layouts put a ref number first).
      let date = null;
      let dateCellIdx = -1;
      for (let i = 0; i < Math.min(2, line.cells.length); i++) {
        // Only look past the first cell when it is a bare reference number, never past text.
        if (i === 1 && /[a-z]/i.test(line.cells[0].str)) break;
        // "7.05" or "12,50" is money, not a date.
        if (i === 1 && parseMoney(line.cells[i].str) && !/\d{4}|[a-z]/i.test(line.cells[i].str) && !/\d+\/\d+/.test(line.cells[i].str)) continue;
        const md = matchDate(line.cells[i].str);
        if (md) {
          date = md.parts;
          dateCellIdx = i;
          // Remaining text in the same cell after the date is description.
          const rest = line.cells[i].str.trim().slice(md.length).trim();
          line._restOfDateCell = rest;
          break;
        }
      }

      // Amount cells: numeric cells to the right of the description.
      const amounts = [];
      const descParts = [];
      line.cells.forEach((c, i) => {
        if (i === dateCellIdx) {
          if (line._restOfDateCell) {
            const tail = splitTrailingMoney(line._restOfDateCell);
            if (tail.desc) descParts.push(tail.desc);
            for (const m of tail.money) amounts.push({ ...m, right: c.x + c.w, x: c.x });
          }
          return;
        }
        const money = parseMoney(c.str);
        if (money) {
          amounts.push({ ...money, right: c.x + c.w, x: c.x });
          return;
        }
        // A cell like "CARD PAYMENT TESCO 12.50" (text and money merged) — split it.
        const tail = splitTrailingMoney(c.str);
        if (tail.money.length && (!cols || isRightOfDescription(c, cols))) {
          if (tail.desc) descParts.push(tail.desc);
          for (const m of tail.money) amounts.push({ ...m, right: c.x + c.w, x: c.x });
          return;
        }
        // A second date cell (e.g. value date) is ignored.
        if (i <= 2 && date && matchDate(c.str) && matchDate(c.str).length === c.str.trim().length) return;
        descParts.push(c.str);
      });
      const description = descParts.join(' ').replace(/\s+/g, ' ').trim();

      // Opening / closing balance lines (with or without dates).
      if (OPENING_RE.test(description || text) && amounts.length) {
        const bal = pickBalance(amounts, cols);
        if (openingBalance === null && bal !== null) openingBalance = bal;
        lastRow = null;
        continue;
      }
      if (CLOSING_RE.test(description || text) && amounts.length) {
        const bal = pickBalance(amounts, cols);
        if (bal !== null) closingBalance = bal;
        lastRow = null;
        continue;
      }
      if (SKIP_RE.test(text)) {
        lastRow = null;
        continue;
      }

      if (date && amounts.length) {
        const row = { page: line.page, date, description, amounts, cols, y: line.y };
        raw.push(row);
        lastRow = row;
      } else if (!date && amounts.length && lastRow && description && lastRow.amounts.length === 0) {
        // Date on a previous line with no amounts (rare): attach.
        lastRow.amounts = amounts;
        lastRow.description = `${lastRow.description} ${description}`.trim();
      } else if (!date && amounts.length && raw.length && description && cols) {
        // Same-day rows where the bank prints the date only once per day.
        const prev = raw[raw.length - 1];
        const row = { page: line.page, date: prev.date, description, amounts, cols, y: line.y, inheritedDate: true };
        raw.push(row);
        lastRow = row;
      } else if (!date && !amounts.length && lastRow && description && line.y - lastRow.y < (line.h || 8) * 2.6) {
        // Continuation line of the description.
        lastRow.description = `${lastRow.description} ${description}`.trim();
        lastRow.y = line.y;
      } else if (date && !amounts.length && description) {
        // Description-only dated row; amounts may follow on the next line.
        const row = { page: line.page, date, description, amounts: [], cols, y: line.y };
        raw.push(row);
        lastRow = row;
      } else {
        lastRow = null;
      }
    }
  }

  const rows = raw.filter((r) => r.amounts.length);
  if (!rows.length) {
    return empty(['No transactions were found. If this is a digital statement, please report the layout so we can support it.']);
  }

  // ---- date order + year ----
  const dateOrder = resolveDateOrder(rows.map((r) => r.date), opts.dateOrder, fullText);
  assignDates(rows, dateOrder, yearHint, warnings);

  // ---- assign amount / balance ----
  for (const r of rows) assignAmounts(r);

  // ---- infer signs using running balance where needed ----
  inferSigns(rows, openingBalance);

  // If the statement is newest-first, balances run backwards; detect and flip for checking.
  const check = reconcile(rows, openingBalance, closingBalance);

  const transactions = rows.map((r, i) => ({
    date: r.iso,
    description: r.description || '(no description)',
    amount: r.amount === null ? null : round2(r.amount),
    balance: r.balance === null ? null : round2(r.balance),
    page: r.page,
    flag: check.badRows.has(i) ? 'balance-mismatch' : r.signGuessed ? 'sign-guessed' : null,
  }));

  if (transactions.some((t) => t.amount === null)) warnings.push('Some rows had an amount we could not classify; they are flagged for review.');
  if (rows.some((r) => r.signGuessed)) warnings.push('Some debit/credit signs were guessed (no balance column to confirm). Please review flagged rows.');

  return { transactions, openingBalance, closingBalance, check: check.summary, dateOrder, warnings };
}

function empty(warnings) {
  return { transactions: [], openingBalance: null, closingBalance: null, check: { status: 'none' }, dateOrder: null, warnings };
}

function isRightOfDescription(cell, cols) {
  const numericLefts = ['debit', 'credit', 'amount', 'balance'].filter((k) => cols[k]).map((k) => cols[k].left);
  if (!numericLefts.length) return true;
  return cell.x + cell.w >= Math.min(...numericLefts) - 5;
}

/** Split "TESCO STORES 12.50 1,234.00" → desc "TESCO STORES", money [12.50, 1234.00]. */
export function splitTrailingMoney(str) {
  const tokens = str.trim().split(/\s+/);
  const money = [];
  while (tokens.length) {
    let found = null;
    // Try joining up to 3 tokens (e.g. "12.00 CR", "( 12.00 )", "£ 12.00").
    for (let n = Math.min(3, tokens.length); n >= 1; n--) {
      const cand = tokens.slice(tokens.length - n).join(' ');
      const pm = parseMoney(cand);
      if (pm && /\d[.,]\d{2}/.test(cand)) {
        found = { pm, n };
        break;
      }
    }
    if (!found) break;
    money.unshift(found.pm);
    tokens.splice(tokens.length - found.n, found.n);
    if (money.length >= 3) break;
  }
  return { desc: tokens.join(' '), money };
}

function pickBalance(amounts, cols) {
  if (cols && cols.balance) {
    const b = nearest(amounts, cols.balance);
    if (b) return signed(b, 1);
  }
  const a = amounts[amounts.length - 1];
  return signed(a, 1);
}

function signed(m, dflt) {
  return m.value * (m.explicitSign || dflt);
}

function nearest(amounts, col) {
  let best = null;
  let bestD = Infinity;
  for (const a of amounts) {
    const d = Math.min(Math.abs(a.right - col.right), Math.abs((a.x + a.right) / 2 - col.center));
    if (d < bestD) {
      best = a;
      bestD = d;
    }
  }
  return bestD < 60 ? best : null;
}

function assignAmounts(r) {
  r.amount = null;
  r.balance = null;
  r.signGuessed = false;
  r.unsigned = false;
  const cols = r.cols;
  const am = r.amounts;

  if (cols && (cols.debit || cols.credit || cols.amount)) {
    // Assign each amount to the closest numeric column by right edge.
    const keys = ['debit', 'credit', 'amount', 'balance'].filter((k) => cols[k]);
    const assigned = {};
    for (const a of am) {
      let bestK = null;
      let bestD = Infinity;
      for (const k of keys) {
        const d = Math.min(Math.abs(a.right - cols[k].right), Math.abs((a.x + a.right) / 2 - cols[k].center));
        if (d < bestD) {
          bestD = d;
          bestK = k;
        }
      }
      if (bestK && !assigned[bestK]) assigned[bestK] = a;
    }
    if (assigned.balance) r.balance = signed(assigned.balance, 1);
    if (assigned.debit && !assigned.credit) r.amount = -assigned.debit.value;
    else if (assigned.credit && !assigned.debit) r.amount = assigned.credit.value;
    else if (assigned.debit && assigned.credit) r.amount = assigned.credit.value - assigned.debit.value;
    else if (assigned.amount) {
      r.amount = signed(assigned.amount, 1);
      r.unsigned = assigned.amount.explicitSign === 0;
    }
    if (r.amount !== null) return;
  }

  // No usable header: positional fallback.
  if (am.length === 1) {
    r.amount = signed(am[0], 1);
    r.unsigned = am[0].explicitSign === 0;
  } else if (am.length === 2) {
    r.amount = signed(am[0], 1);
    r.unsigned = am[0].explicitSign === 0;
    r.balance = signed(am[1], 1);
  } else {
    // debit, credit, balance — whichever of the first two is present
    r.amount = signed(am[am.length - 2], 1);
    r.unsigned = am[am.length - 2].explicitSign === 0;
    r.balance = signed(am[am.length - 1], 1);
  }
}

function inferSigns(rows, opening) {
  const haveBalances = rows.filter((r) => r.balance !== null).length >= Math.max(2, rows.length * 0.5);
  if (!haveBalances) {
    // Without balances we can only use keyword hints for unsigned single-column amounts.
    for (const r of rows) {
      if (r.unsigned && r.amount !== null) {
        if (/\b(deposit|credit|refund|salary|payroll|interest\s*paid|transfer\s*from|received|payment\s*received|reversal)\b/i.test(r.description)) r.amount = Math.abs(r.amount);
        else r.amount = -Math.abs(r.amount);
        r.signGuessed = true;
      }
    }
    return;
  }
  // Determine chronological direction: does balance[i] ≈ balance[i-1] ± |amount[i]| (oldest first)
  // or balance[i-1] ≈ balance[i] ± |amount[i-1]| (newest first)?
  let fwd = 0;
  let bwd = 0;
  for (let i = 1; i < rows.length; i++) {
    const a = rows[i - 1];
    const b = rows[i];
    if (a.balance === null || b.balance === null) continue;
    if (b.amount !== null && near(Math.abs(b.balance - a.balance), Math.abs(b.amount))) fwd++;
    if (a.amount !== null && near(Math.abs(a.balance - b.balance), Math.abs(a.amount))) bwd++;
  }
  const newestFirst = bwd > fwd;
  if (newestFirst) for (const r of rows) r._newestFirst = true;

  let prevBal = newestFirst ? null : opening;
  const order = newestFirst ? [...rows].reverse() : rows;
  for (const r of order) {
    if (r.unsigned && r.amount !== null && prevBal !== null && r.balance !== null) {
      const delta = round2(r.balance - prevBal);
      if (near(Math.abs(delta), Math.abs(r.amount))) r.amount = Math.sign(delta || 1) * Math.abs(r.amount);
      else {
        r.amount = -Math.abs(r.amount);
        r.signGuessed = true;
      }
    } else if (r.unsigned && r.amount !== null && r.balance !== null && prevBal === null) {
      // First row with no opening balance: resolve from the next row later; tentatively debit.
      r._needsNext = true;
    }
    if (r.balance !== null) prevBal = r.balance;
    else if (prevBal !== null && r.amount !== null) prevBal = round2(prevBal + r.amount);
  }
  // Resolve a leading row lacking a previous balance: its sign can't be proven, but if the
  // statement has an opening balance missing we back-compute and mark as guessed only if ambiguous.
  for (const r of order) {
    if (r._needsNext) {
      r.amount = /\b(deposit|credit|refund|salary|payroll|received)\b/i.test(r.description) ? Math.abs(r.amount) : -Math.abs(r.amount);
      r.signGuessed = true;
    }
  }
}

function near(a, b) {
  return Math.abs(a - b) < 0.015;
}

function reconcile(rows, opening, closing) {
  const badRows = new Set();
  const withBal = rows.filter((r) => r.balance !== null).length;
  if (withBal < 2 && opening === null) {
    const total = round2(rows.reduce((s, r) => s + (r.amount || 0), 0));
    const summary = { status: 'unverified', message: 'No running balance on this statement, so totals cannot be verified automatically.', net: total };
    if (opening !== null && closing !== null) {
      const ok = near(round2(opening + total), closing);
      summary.status = ok ? 'ok' : 'mismatch';
      summary.message = ok ? 'Opening + transactions = closing balance.' : `Opening + transactions ≠ closing balance (off by ${round2(closing - opening - total)}).`;
    }
    return { badRows, summary };
  }
  const newestFirst = rows[0]?._newestFirst;
  const idx = rows.map((_, i) => i);
  if (newestFirst) idx.reverse();
  let prev = newestFirst ? null : opening;
  let checked = 0;
  for (const i of idx) {
    const r = rows[i];
    if (prev !== null && r.amount !== null && r.balance !== null) {
      checked++;
      if (!near(round2(prev + r.amount), r.balance)) badRows.add(i);
    }
    if (r.balance !== null) prev = r.balance;
    else if (prev !== null && r.amount !== null) prev = round2(prev + r.amount);
  }
  const net = round2(rows.reduce((s, r) => s + (r.amount || 0), 0));
  let closingOk = null;
  if (opening !== null && closing !== null) closingOk = near(round2(opening + net), closing);
  const status = badRows.size === 0 && closingOk !== false ? 'ok' : 'mismatch';
  const parts = [];
  if (status === 'ok') parts.push(`All ${checked} running balances verified${closingOk ? ', and opening + transactions = closing balance' : ''}.`);
  else {
    if (badRows.size) parts.push(`${badRows.size} row(s) do not match the running balance — review highlighted rows.`);
    if (closingOk === false) parts.push(`Opening + transactions ≠ closing balance (off by ${round2(closing - opening - net)}).`);
  }
  return { badRows, summary: { status, message: parts.join(' '), checked, net, newestFirst: !!newestFirst } };
}

function guessYear(text) {
  const years = [...text.matchAll(/\b(20\d{2}|19\d{2})\b/g)].map((m) => +m[1]).filter((y) => y >= 1990 && y <= 2100);
  if (!years.length) return new Date().getFullYear();
  const counts = {};
  for (const y of years) counts[y] = (counts[y] || 0) + 1;
  return +Object.entries(counts).sort((a, b) => b[1] - a[1] || b[0] - a[0])[0][0];
}

function resolveDateOrder(dates, requested, text) {
  if (requested === 'DMY' || requested === 'MDY') return requested;
  let dmy = 0;
  let mdy = 0;
  for (const d of dates) {
    if (d.a === undefined) continue;
    if (d.a > 12) dmy++;
    if (d.b > 12) mdy++;
  }
  if (dmy > mdy) return 'DMY';
  if (mdy > dmy) return 'MDY';
  // Ambiguous: guess from currency / locale cues.
  if (/[£€]|\bGBP\b|\bEUR\b|sort\s*code|\bIBAN\b|\bAUD\b|\bNZD\b|\bINR\b|\bZAR\b/i.test(text)) return 'DMY';
  return 'MDY';
}

function assignDates(rows, order, yearHint, warnings) {
  // Fill in missing years; handle Dec→Jan rollover (oldest-first) or Jan→Dec (newest-first).
  let year = yearHint;
  const parsed = rows.map((r) => {
    const p = r.date;
    let m;
    let d;
    if (p.a !== undefined) {
      [d, m] = order === 'DMY' ? [p.a, p.b] : [p.b, p.a];
    } else {
      m = p.m;
      d = p.d;
    }
    return { m, d, y: p.y };
  });
  const explicitYears = parsed.filter((p) => p.y);
  if (explicitYears.length === 0) {
    // Statement crossing a year end: months jump from 12 → 1. Start in yearHint-1 if that happens.
    const months = parsed.map((p) => p.m);
    const crosses = months.some((m, i) => i > 0 && months[i - 1] === 12 && m === 1);
    const crossesBack = months.some((m, i) => i > 0 && months[i - 1] === 1 && m === 12);
    year = crosses ? yearHint - 1 : yearHint;
    let prevM = null;
    for (const p of parsed) {
      if (prevM !== null && prevM === 12 && p.m === 1 && crosses) year++;
      if (prevM !== null && prevM === 1 && p.m === 12 && crossesBack) year--;
      p.y = year;
      prevM = p.m;
    }
  } else {
    let lastY = explicitYears[0].y;
    for (const p of parsed) {
      if (p.y) lastY = p.y;
      else p.y = lastY;
    }
  }
  rows.forEach((r, i) => {
    const p = parsed[i];
    const valid = p.m >= 1 && p.m <= 12 && p.d >= 1 && p.d <= 31;
    r.iso = valid ? `${p.y}-${String(p.m).padStart(2, '0')}-${String(p.d).padStart(2, '0')}` : null;
  });
  if (rows.some((r) => !r.iso)) warnings.push('Some dates could not be read.');
}
