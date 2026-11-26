// Signed, stateless license keys: SK1.<base64url(payload)>.<base64url(hmac)>
// payload = { e: email, x: expiry (ms epoch), p: plan }
import { createHmac, timingSafeEqual } from 'node:crypto';

const b64u = (buf) => Buffer.from(buf).toString('base64url');

export function issueKey(secret, { email, days, plan = 'pro', from = Date.now() }) {
  if (!secret) throw new Error('LICENSE_SECRET is not set');
  const payload = b64u(JSON.stringify({ e: email, x: from + days * 86400000, p: plan }));
  const sig = b64u(createHmac('sha256', secret).update(payload).digest());
  return `SK1.${payload}.${sig}`;
}

export function verifyKey(secret, key, now = Date.now()) {
  if (!secret || typeof key !== 'string') return { valid: false, reason: 'missing' };
  const [ver, payload, sig] = key.trim().split('.');
  if (ver !== 'SK1' || !payload || !sig) return { valid: false, reason: 'format' };
  const expected = createHmac('sha256', secret).update(payload).digest();
  const given = Buffer.from(sig, 'base64url');
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return { valid: false, reason: 'signature' };
  let data;
  try {
    data = JSON.parse(Buffer.from(payload, 'base64url').toString());
  } catch {
    return { valid: false, reason: 'format' };
  }
  if (typeof data.x !== 'number' || data.x < now) return { valid: false, reason: 'expired', expires: data.x };
  return { valid: true, email: data.e, expires: data.x, plan: data.p };
}
