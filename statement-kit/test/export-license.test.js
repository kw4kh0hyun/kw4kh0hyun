import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exportTransactions } from '../lib/export.js';
import { issueKey, verifyKey } from '../lib/license.js';

const txs = [
  { date: '2026-03-02', description: 'TESCO, "STORES"', amount: -12.5, balance: 100 },
  { date: '2026-03-03', description: '=HYPERLINK("x")', amount: 200, balance: 300 },
];

test('CSV escapes quotes/commas and neutralises formula injection', () => {
  const out = exportTransactions('csv', txs);
  const lines = out.trim().split('\r\n');
  assert.equal(lines[0], 'Date,Description,Debit,Credit,Amount,Balance');
  assert.equal(lines[1], '2026-03-02,"TESCO, ""STORES""",12.50,,-12.50,100.00');
  assert.ok(lines[2].startsWith(`2026-03-03,"'=HYPERLINK`));
});

test('QuickBooks CSV uses MM/DD/YYYY and signed amounts', () => {
  const lines = exportTransactions('quickbooks', txs).trim().split('\r\n');
  assert.equal(lines[1], '03/02/2026,"TESCO, ""STORES""",-12.50');
});

test('OFX has one STMTTRN per row with stable FITIDs', () => {
  const a = exportTransactions('ofx', txs, { currency: 'GBP' });
  const b = exportTransactions('ofx', txs, { currency: 'GBP' });
  assert.equal(a, b);
  assert.equal((a.match(/<STMTTRN>/g) || []).length, 2);
  assert.match(a, /<TRNTYPE>DEBIT<DTPOSTED>20260302<TRNAMT>-12.50/);
  assert.match(a, /<CURDEF>GBP/);
});

test('QIF output', () => {
  assert.match(exportTransactions('qif', txs), /^!Type:Bank\nD03\/02\/2026\nT-12.50\nPTESCO/);
});

test('license keys verify, expire, and reject tampering', () => {
  const key = issueKey('s3cret', { email: 'a@b.c', days: 30 });
  const v = verifyKey('s3cret', key);
  assert.equal(v.valid, true);
  assert.equal(v.email, 'a@b.c');
  assert.equal(verifyKey('other', key).valid, false);
  const [p0, payload, sig] = key.split('.');
  const forged = Buffer.from(JSON.stringify({ e: 'a@b.c', x: Date.now() + 9e12, p: 'pro' })).toString('base64url');
  assert.equal(verifyKey('s3cret', `${p0}.${forged}.${sig}`).valid, false);
  assert.equal(verifyKey('s3cret', key, Date.now() + 31 * 86400000).reason, 'expired');
  void payload;
});
