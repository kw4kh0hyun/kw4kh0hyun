// Export transactions to formats accounting tools import.
// tx: { date: 'YYYY-MM-DD', description, amount, balance }

const csvCell = (v) => {
  if (v === null || v === undefined) return '';
  const s = String(v);
  // Guard against CSV/formula injection when opened in Excel/Sheets.
  const safe = /^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};
const csv = (rows) => rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
const fmt = (n) => (n === null || n === undefined ? '' : n.toFixed(2));
const usDate = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}` : '');
const ukDate = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '');

export const FORMATS = {
  csv: { label: 'CSV (Excel / Google Sheets)', ext: 'csv', mime: 'text/csv', pro: false },
  quickbooks: { label: 'QuickBooks Online CSV', ext: 'csv', mime: 'text/csv', pro: true },
  xero: { label: 'Xero CSV', ext: 'csv', mime: 'text/csv', pro: true },
  ofx: { label: 'OFX (QuickBooks, Xero, Quicken, YNAB…)', ext: 'ofx', mime: 'application/x-ofx', pro: true },
  qif: { label: 'QIF (Quicken, older tools)', ext: 'qif', mime: 'application/qif', pro: true },
};

export function exportTransactions(format, txs, opts = {}) {
  const t = txs.filter((x) => x.date && x.amount !== null);
  switch (format) {
    case 'csv':
      return csv([['Date', 'Description', 'Debit', 'Credit', 'Amount', 'Balance'], ...txs.map((x) => [x.date, x.description, x.amount < 0 ? fmt(-x.amount) : '', x.amount > 0 ? fmt(x.amount) : '', fmt(x.amount), fmt(x.balance)])]);
    case 'quickbooks':
      // QBO 3-column format: Date, Description, Amount (dates in MM/DD/YYYY).
      return csv([['Date', 'Description', 'Amount'], ...t.map((x) => [usDate(x.date), x.description, fmt(x.amount)])]);
    case 'xero':
      // Xero precoded statement import: Date, Amount, Payee, Description, Reference.
      return csv([['*Date', '*Amount', 'Payee', 'Description', 'Reference'], ...t.map((x) => [opts.dateOrder === 'MDY' ? usDate(x.date) : ukDate(x.date), fmt(x.amount), x.description.slice(0, 60), x.description, ''])]);
    case 'qif':
      return `!Type:Bank\n${t.map((x) => `D${usDate(x.date)}\nT${fmt(x.amount)}\nP${x.description.replace(/\n/g, ' ')}\n^`).join('\n')}\n`;
    case 'ofx':
      return toOfx(t, opts);
    default:
      throw new Error(`Unknown format ${format}`);
  }
}

function ofxEsc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fitid(x, i) {
  // Stable id from content so re-imports dedupe correctly.
  let h = 2166136261;
  const s = `${x.date}|${x.amount}|${x.description}|${i}`;
  for (let k = 0; k < s.length; k++) {
    h ^= s.charCodeAt(k);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return `${x.date.replace(/-/g, '')}${h.toString(16).padStart(8, '0')}`;
}

function toOfx(t, opts) {
  const d = (iso) => iso.replace(/-/g, '');
  const start = t.length ? t.map((x) => x.date).sort()[0] : '1970-01-01';
  const end = t.length ? t.map((x) => x.date).sort().at(-1) : '1970-01-01';
  const lastBal = [...t].reverse().find((x) => x.balance !== null)?.balance ?? opts.closingBalance ?? 0;
  const body = t
    .map((x, i) => `<STMTTRN><TRNTYPE>${x.amount < 0 ? 'DEBIT' : 'CREDIT'}<DTPOSTED>${d(x.date)}<TRNAMT>${fmt(x.amount)}<FITID>${fitid(x, i)}<NAME>${ofxEsc(x.description.slice(0, 32))}<MEMO>${ofxEsc(x.description)}</STMTTRN>`)
    .join('\n');
  return `OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>${d(end)}<LANGUAGE>ENG</SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS><CURDEF>${opts.currency || 'USD'}
<BANKACCTFROM><BANKID>000000000<ACCTID>${opts.accountId || 'STATEMENT'}<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>${d(start)}<DTEND>${d(end)}
${body}
</BANKTRANLIST><LEDGERBAL><BALAMT>${fmt(lastBal)}<DTASOF>${d(end)}</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
`;
}
