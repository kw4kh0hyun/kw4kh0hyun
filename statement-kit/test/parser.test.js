import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as F from './fixtures.js';
import { pagesFromBuffer } from './helpers.js';
import { parseStatement, parseMoney, matchDate, splitTrailingMoney } from '../lib/parser.js';

const data = F.makeTransactions(70);

function assertMatches(result, expected) {
  assert.equal(result.transactions.length, expected.length, 'row count');
  result.transactions.forEach((t, i) => {
    const e = expected[i];
    assert.equal(t.date, F.iso(e), `date row ${i}`);
    assert.ok(Math.abs(t.amount - e.amount) < 0.001, `amount row ${i}: ${t.amount} vs ${e.amount}`);
    assert.ok(Math.abs(t.balance - e.balance) < 0.001, `balance row ${i}`);
    assert.ok(t.description.startsWith(e.desc), `desc row ${i}: ${t.description}`);
  });
}

test('UK layout: Paid out/Paid in columns, once-per-day dates, wrapped lines, multi-page', async () => {
  const r = parseStatement(await pagesFromBuffer(await F.ukStatement(data)));
  assertMatches(r, data.txs);
  assert.equal(r.openingBalance, data.opening);
  assert.equal(r.closingBalance, data.closing);
  assert.equal(r.check.status, 'ok');
  assert.equal(r.dateOrder, 'DMY');
  assert.match(r.transactions[1].description, /REF 88231 VIA MOBILE/, 'continuation line appended');
});

test('US layout: signed Amount column, $ amounts, MM/DD dates', async () => {
  const r = parseStatement(await pagesFromBuffer(await F.usStatement(data)));
  assertMatches(r, data.txs);
  assert.equal(r.check.status, 'ok');
  assert.equal(r.dateOrder, 'MDY');
});

test('Newest-first statements are detected and still verified', async () => {
  const r = parseStatement(await pagesFromBuffer(await F.usStatement(data, { newestFirst: true })));
  assertMatches(r, [...data.txs].reverse());
  assert.equal(r.check.status, 'ok');
  assert.equal(r.check.newestFirst, true);
});

test('Headerless EU layout: 1.234,56 numbers, unsigned amounts, signs inferred from balance', async () => {
  const r = parseStatement(await pagesFromBuffer(await F.euStatement(data)));
  assertMatches(r, data.txs);
  assert.equal(r.check.status, 'ok');
  // Only the first row lacks a previous balance, so only it may be guessed.
  assert.ok(r.transactions.slice(1).every((t) => t.flag === null));
});

test('Image-only PDF reports missing text layer', async () => {
  const r = parseStatement(await pagesFromBuffer(await F.imageOnlyPdf()));
  assert.equal(r.transactions.length, 0);
  assert.match(r.warnings[0], /no text layer/);
});

test('Tampered amount is caught by balance reconciliation', async () => {
  const pages = await pagesFromBuffer(await F.usStatement(data));
  const victim = pages[0].items.find((i) => i.str === `-$${Math.abs(data.txs[5].amount).toFixed(2)}`);
  assert.ok(victim, 'found amount item to tamper');
  victim.str = '-$999.99';
  const r = parseStatement(pages);
  assert.equal(r.check.status, 'mismatch');
  assert.equal(r.transactions[5].flag, 'balance-mismatch');
});

test('parseMoney handles common formats', () => {
  const cases = [
    ['1,234.56', 1234.56, 0], ['-12.00', 12, -1], ['(45.10)', 45.1, -1], ['12.00-', 12, -1], ['£1,000.00', 1000, 0],
    ['$5.25', 5.25, 0], ['1.234,56', 1234.56, 0], ['99.00 CR', 99, 1], ['99.00 DR', 99, -1], ['-$1,050.75', 1050.75, -1], ['+20.00', 20, 1],
  ];
  for (const [s, v, sign] of cases) {
    const m = parseMoney(s);
    assert.ok(m, s);
    assert.equal(m.value, v, s);
    assert.equal(m.explicitSign, sign, s);
  }
  for (const s of ['ACME', '12345678', '2026', '12-34-56', 'Page 1']) assert.equal(parseMoney(s), null, s);
});

test('matchDate handles common formats', () => {
  assert.deepEqual(matchDate('2026-03-05').parts, { y: 2026, m: 3, d: 5 });
  assert.deepEqual(matchDate('05/03/2026').parts, { a: 5, b: 3, y: 2026 });
  assert.deepEqual(matchDate('5 Mar').parts, { d: 5, m: 3, y: null });
  assert.deepEqual(matchDate('05 March 2026 CARD').parts, { d: 5, m: 3, y: 2026 });
  assert.deepEqual(matchDate('Mar 5, 2026').parts, { m: 3, d: 5, y: 2026 });
  assert.deepEqual(matchDate('03/05').parts, { a: 3, b: 5, y: null });
  assert.equal(matchDate('TESCO'), null);
  assert.equal(matchDate('45/67'), null);
});

test('splitTrailingMoney separates merged description and amounts', () => {
  const r = splitTrailingMoney('CARD PAYMENT TESCO 12.50 1,234.00');
  assert.equal(r.desc, 'CARD PAYMENT TESCO');
  assert.deepEqual(r.money.map((m) => m.value), [12.5, 1234]);
});
