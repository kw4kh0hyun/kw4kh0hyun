// StatementKit server. Statements are NEVER sent here — the browser parses them locally.
// This server only serves static files and issues/verifies Pro license keys.
//
//   GET  /api/config                       → pricing + checkout link
//   GET  /api/license/claim?session_id=…   → verifies a paid Stripe Checkout session, returns a key
//   POST /api/license/verify {key}         → { valid, expires }
//
// Env: PORT, LICENSE_SECRET, STRIPE_SECRET_KEY, STRIPE_PAYMENT_LINK, PASS_DAYS (30), PRICE_LABEL ("$9")
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { issueKey, verifyKey } from './lib/license.js';

const DIR = fileURLToPath(new URL('.', import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const SECRET = process.env.LICENSE_SECRET || '';
const PASS_DAYS = Number(process.env.PASS_DAYS) || 30;
const PRICE_LABEL = process.env.PRICE_LABEL || '$9';

if (!SECRET) console.warn('[statement-kit] LICENSE_SECRET not set — Pro keys cannot be issued or verified.');

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml' };

// Strict CSP: the page can only talk to this origin, so statement data has nowhere to go.
const SECURITY_HEADERS = {
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; worker-src 'self' blob:; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
};

// Files outside public/ that the browser may load.
const MAPPED = {
  '/lib/parser.js': 'lib/parser.js',
  '/lib/export.js': 'lib/export.js',
  '/lib/pdf-text.js': 'lib/pdf-text.js',
  '/vendor/pdf.min.mjs': 'node_modules/pdfjs-dist/build/pdf.min.mjs',
  '/vendor/pdf.worker.min.mjs': 'node_modules/pdfjs-dist/build/pdf.worker.min.mjs',
};

function send(res, status, body, type = 'application/json; charset=utf-8', extra = {}) {
  res.writeHead(status, { 'Content-Type': type, ...SECURITY_HEADERS, ...extra });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

// Tiny per-IP rate limit for license endpoints.
const hits = new Map();
function limited(req) {
  const ip = req.socket.remoteAddress || '?';
  const now = Date.now();
  const h = (hits.get(ip) || []).filter((t) => now - t < 60000);
  h.push(now);
  hits.set(ip, h);
  if (hits.size > 5000) hits.clear();
  return h.length > 30;
}

async function readBody(req, max = 4096) {
  let data = '';
  for await (const chunk of req) {
    data += chunk;
    if (data.length > max) throw new Error('too large');
  }
  return data;
}

async function claim(sessionId) {
  if (!process.env.STRIPE_SECRET_KEY || !SECRET) return { status: 503, body: { error: 'Payments are not configured on this server.' } };
  if (!/^cs_(test|live)_[A-Za-z0-9]+$/.test(sessionId || '')) return { status: 400, body: { error: 'Invalid session id.' } };
  const r = await fetch(`https://api.stripe.com/v1/checkout/sessions/${sessionId}`, { headers: { Authorization: `Bearer ${process.env.STRIPE_SECRET_KEY}` } });
  if (!r.ok) return { status: 404, body: { error: 'Checkout session not found.' } };
  const s = await r.json();
  if (s.payment_status !== 'paid') return { status: 402, body: { error: 'Payment not completed yet.' } };
  const email = s.customer_details?.email || s.customer_email || 'customer';
  // Expiry counts from purchase time, so re-claiming the same session gives the same expiry.
  const key = issueKey(SECRET, { email, days: PASS_DAYS, from: s.created * 1000 });
  return { status: 200, body: { key, email, ...verifyKey(SECRET, key) } };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const p = url.pathname;
  try {
    if (p === '/api/config') {
      return send(res, 200, { checkoutUrl: process.env.STRIPE_PAYMENT_LINK || null, price: PRICE_LABEL, passDays: PASS_DAYS }, undefined, { 'Cache-Control': 'no-store' });
    }
    if (p === '/api/license/claim') {
      if (limited(req)) return send(res, 429, { error: 'Too many requests' });
      const { status, body } = await claim(url.searchParams.get('session_id'));
      return send(res, status, body, undefined, { 'Cache-Control': 'no-store' });
    }
    if (p === '/api/license/verify' && req.method === 'POST') {
      if (limited(req)) return send(res, 429, { error: 'Too many requests' });
      let key = '';
      try {
        key = JSON.parse(await readBody(req)).key;
      } catch {
        return send(res, 400, { valid: false, reason: 'bad request' });
      }
      const v = verifyKey(SECRET, key);
      return send(res, 200, { valid: v.valid, expires: v.expires, reason: v.reason }, undefined, { 'Cache-Control': 'no-store' });
    }
    if (p.startsWith('/api/')) return send(res, 404, { error: 'Not found' });
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405, 'Method not allowed', 'text/plain');

    let file;
    if (MAPPED[p]) file = join(DIR, MAPPED[p]);
    else {
      const rel = normalize(p === '/' ? '/index.html' : p).replace(/^(\.\.[/\\])+/, '');
      file = join(DIR, 'public', rel);
      if (!file.startsWith(join(DIR, 'public'))) return send(res, 403, 'Forbidden', 'text/plain');
    }
    const buf = await readFile(file);
    const cache = p.startsWith('/vendor/') ? 'public, max-age=604800, immutable' : 'no-cache';
    return send(res, 200, buf, TYPES[extname(file)] || 'application/octet-stream', { 'Cache-Control': cache });
  } catch (e) {
    if (e.code === 'ENOENT' || e.code === 'EISDIR') return send(res, 404, 'Not found', 'text/plain');
    console.error(e);
    return send(res, 500, { error: 'Server error' });
  }
});

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  server.listen(PORT, () => console.log(`StatementKit on http://localhost:${PORT}`));
}
export { server };
