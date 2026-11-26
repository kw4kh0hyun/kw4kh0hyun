// Generates realistic synthetic bank statement PDFs in several common layouts.
import PDFDocument from 'pdfkit';

function toBuffer(doc) {
  return new Promise((resolve) => {
    const chunks = [];
    doc.on('data', (c) => chunks.push(c));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.end();
  });
}

const money = (n, { cur = '', sep = ',' } = {}) =>
  cur + Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, sep);

function rightText(doc, text, right, y) {
  const w = doc.widthOfString(text);
  doc.text(text, right - w, y, { lineBreak: false });
}

/** Deterministic transaction list. */
export function makeTransactions(n, { start = [2026, 3, 1], seed = 7, opening = 2500 } = {}) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  const payees = ['TESCO STORES 3112', 'AMAZON MKTPLACE PMTS', 'SHELL FUEL 0045', 'NETFLIX.COM', 'TFL TRAVEL CHARGE', 'DIRECT DEBIT COUNCIL TAX', 'CARD PAYMENT TO PRET A MANGER', 'STANDING ORDER RENT FLAT 2'];
  const txs = [];
  let bal = opening;
  let day = start[2];
  let month = start[1];
  let year = start[0];
  for (let i = 0; i < n; i++) {
    if (rnd() > 0.5) day++;
    if (day > 28) {
      day = 1;
      month++;
      if (month > 12) {
        month = 1;
        year++;
      }
    }
    const credit = i % 7 === 3;
    const amount = credit ? Math.round(rnd() * 150000) / 100 + 500 : -(Math.round(rnd() * 20000) / 100 + 1);
    bal = Math.round((bal + amount) * 100) / 100;
    const desc = credit ? (i % 2 ? 'SALARY ACME LTD' : 'FASTER PAYMENT RECEIVED J SMITH') : payees[Math.floor(rnd() * payees.length)];
    txs.push({ y: year, m: month, d: day, desc, amount, balance: bal });
  }
  return { txs, opening, closing: bal };
}

const iso = (t) => `${t.y}-${String(t.m).padStart(2, '0')}-${String(t.d).padStart(2, '0')}`;
export { iso };
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** UK style: "02 Mar" dates, Paid out / Paid in / Balance columns, £, multi-page, wrapped descriptions. */
export async function ukStatement(data) {
  const doc = new PDFDocument({ size: 'A4', margin: 40 });
  const header = (y) => {
    doc.font('Helvetica-Bold').fontSize(9);
    doc.text('Date', 40, y);
    doc.text('Description', 100, y);
    rightText(doc, 'Paid out', 390, y);
    rightText(doc, 'Paid in', 470, y);
    rightText(doc, 'Balance', 555, y);
    doc.font('Helvetica').fontSize(9);
  };
  doc.font('Helvetica-Bold').fontSize(14).text('Example Bank plc', 40, 40);
  doc.font('Helvetica').fontSize(9).text(`Statement period 01 March ${data.txs[0].y} to 30 April ${data.txs[0].y}`, 40, 62);
  doc.text('Sort code 12-34-56   Account number 12345678', 40, 74);
  let y = 110;
  header(y);
  y += 16;
  doc.text('', 40, y);
  doc.text('Balance brought forward', 100, y);
  rightText(doc, money(data.opening), 555, y);
  y += 14;
  let lastDate = null;
  data.txs.forEach((t, i) => {
    if (y > 760) {
      doc.text('Page continued', 40, 800);
      doc.addPage();
      y = 60;
      header(y);
      y += 16;
    }
    const ds = `${String(t.d).padStart(2, '0')} ${MON[t.m - 1]}`;
    // Print the date only once per day, like many UK banks.
    if (ds !== lastDate) doc.text(ds, 40, y);
    lastDate = ds;
    doc.text(t.desc, 100, y, { lineBreak: false });
    if (t.amount < 0) rightText(doc, money(t.amount), 390, y);
    else rightText(doc, money(t.amount), 470, y);
    rightText(doc, money(t.balance), 555, y);
    y += 12;
    if (i % 5 === 1) {
      doc.fillColor('#555').text('REF 88231 VIA MOBILE', 100, y, { lineBreak: false }).fillColor('#000');
      y += 12;
    }
  });
  doc.text('', 40, y);
  doc.text('Balance carried forward', 100, y);
  rightText(doc, money(data.closing), 555, y);
  return toBuffer(doc);
}

/** US style: MM/DD dates, single signed Amount column + Balance, $ sign, newest-first option. */
export async function usStatement(data, { newestFirst = false } = {}) {
  const doc = new PDFDocument({ size: 'LETTER', margin: 40 });
  doc.font('Helvetica-Bold').fontSize(14).text('First Example Bank, N.A.', 40, 40);
  doc.font('Helvetica').fontSize(9).text(`Statement Period: 03/01/${data.txs[0].y} - 04/30/${data.txs[0].y}`, 40, 62);
  let y = 100;
  doc.font('Helvetica-Bold');
  doc.text('Posting Date', 40, y);
  doc.text('Description', 120, y);
  rightText(doc, 'Amount', 470, y);
  rightText(doc, 'Balance', 570, y);
  doc.font('Helvetica');
  y += 16;
  doc.text(`Beginning Balance`, 120, y);
  rightText(doc, money(data.opening, { cur: '$' }), 570, y);
  y += 14;
  const list = newestFirst ? [...data.txs].reverse() : data.txs;
  for (const t of list) {
    if (y > 740) {
      doc.addPage();
      y = 60;
    }
    doc.text(`${String(t.m).padStart(2, '0')}/${String(t.d).padStart(2, '0')}`, 40, y);
    doc.text(t.desc, 120, y, { lineBreak: false });
    rightText(doc, (t.amount < 0 ? '-' : '') + money(t.amount, { cur: '$' }), 470, y);
    rightText(doc, money(t.balance, { cur: '$' }), 570, y);
    y += 13;
  }
  y += 6;
  doc.text('Ending Balance', 120, y);
  rightText(doc, money(data.closing, { cur: '$' }), 570, y);
  return toBuffer(doc);
}

/** Headerless, European numbers: DD.MM.YYYY, "1.234,56", unsigned amount + balance (signs must be inferred). */
export async function euStatement(data) {
  const doc = new PDFDocument({ size: 'A4', margin: 40 });
  doc.fontSize(12).text('Beispielbank AG — Kontoauszug', 40, 40);
  doc.fontSize(9).text('IBAN DE00 1234 5678 9012 3456 78', 40, 58);
  let y = 100;
  for (const t of data.txs) {
    if (y > 760) {
      doc.addPage();
      y = 60;
    }
    doc.text(`${String(t.d).padStart(2, '0')}.${String(t.m).padStart(2, '0')}.${t.y}`, 40, y);
    doc.text(t.desc, 110, y, { lineBreak: false });
    rightText(doc, money(t.amount, { sep: '.' }).replace(/\.(\d{2})$/, ',$1'), 440, y);
    rightText(doc, money(t.balance, { sep: '.' }).replace(/\.(\d{2})$/, ',$1'), 550, y);
    y += 13;
  }
  return toBuffer(doc);
}

/** Scanned-like PDF: no text layer at all. */
export async function imageOnlyPdf() {
  const doc = new PDFDocument({ size: 'A4' });
  doc.rect(50, 50, 400, 300).fill('#ccc');
  return toBuffer(doc);
}
