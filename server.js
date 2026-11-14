// Song DNA 프로토타입 서버 (의존성 없음, Node 18+)
//   GET /api/resolve?q=<링크 또는 검색어>  → 곡 메타데이터(JSON)
//   GET /api/media?url=<미리듣기/이미지 URL> → CORS 우회용 미디어 프록시(허용 호스트만)
//   그 외 → public/ 정적 파일
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Readable } from 'node:stream';
import { resolve, ResolveError } from './lib/resolve.js';

const PORT = Number(process.env.PORT) || 3000;
const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), 'public');

// 오픈 프록시가 되지 않도록 음원/이미지 CDN만 허용
const MEDIA_HOSTS = ['dzcdn.net', 'deezer.com', 'mzstatic.com', 'apple.com', 'scdn.co', 'spotifycdn.com', 'ytimg.com'];
export const isAllowedMedia = (u) => {
  try {
    const { protocol, hostname } = new URL(u);
    return protocol === 'https:' && MEDIA_HOSTS.some((h) => hostname === h || hostname.endsWith(`.${h}`));
  } catch {
    return false;
  }
};

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.json': 'application/json',
};

const cache = new Map(); // 간단한 메모리 캐시 (resolve 결과)

function sendJson(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

async function handleResolve(req, res, q) {
  try {
    const key = q.trim();
    if (!cache.has(key)) cache.set(key, await resolve(key));
    if (cache.size > 200) cache.delete(cache.keys().next().value);
    sendJson(res, 200, cache.get(key));
  } catch (e) {
    cache.delete(q.trim());
    const status = e instanceof ResolveError ? e.status : 502;
    const message = e instanceof ResolveError ? e.message : `외부 서비스에 연결하지 못했어요: ${e.message}`;
    sendJson(res, status, { error: message });
  }
}

async function handleMedia(req, res, target) {
  if (!isAllowedMedia(target)) return sendJson(res, 403, { error: '허용되지 않은 미디어 주소예요.' });
  try {
    const upstream = await fetch(target, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; SongDNA/0.1)' } });
    if (!upstream.ok || !upstream.body) return sendJson(res, 502, { error: `미디어 응답 오류 (${upstream.status})` });
    res.writeHead(200, {
      'Content-Type': upstream.headers.get('content-type') || 'application/octet-stream',
      'Cache-Control': 'public, max-age=86400',
    });
    Readable.fromWeb(upstream.body).pipe(res);
  } catch (e) {
    sendJson(res, 502, { error: `미디어를 가져오지 못했어요: ${e.message}` });
  }
}

async function handleStatic(req, res, pathname) {
  const rel = normalize(decodeURIComponent(pathname === '/' ? '/index.html' : pathname)).replace(/^(\.\.[/\\])+/, '');
  const file = join(ROOT, rel);
  if (!file.startsWith(ROOT)) return sendJson(res, 403, { error: 'forbidden' });
  try {
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
    res.end(data);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not found');
  }
}

export const server = http.createServer((req, res) => {
  const { pathname, searchParams } = new URL(req.url, 'http://localhost');
  if (pathname === '/api/resolve') return handleResolve(req, res, searchParams.get('q') || '');
  if (pathname === '/api/media') return handleMedia(req, res, searchParams.get('url') || '');
  return handleStatic(req, res, pathname);
});

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  server.listen(PORT, () => console.log(`🎧 Song DNA → http://localhost:${PORT}`));
}
