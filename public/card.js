// Song DNA 카드(1080×1920, 인스타 스토리 비율) 캔버스 렌더러 + 앨범아트 팔레트 추출
import { fmtTime } from './analysis.js';

const FONT = '"Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif';
export const AXES = [
  ['energy', '에너지'],
  ['danceability', '댄스'],
  ['valence', '긍정감'],
  ['brightness', '밝기'],
  ['tempo', '템포'],
  ['dynamics', '다이내믹'],
];

const MOOD_FALLBACK = {
  euphoric: [[255, 94, 98], [255, 175, 64], [255, 225, 120], [120, 60, 160], [40, 20, 60]],
  intense: [[200, 30, 60], [90, 20, 120], [255, 90, 40], [30, 10, 40], [140, 140, 160]],
  warm: [[255, 170, 120], [250, 220, 170], [120, 180, 160], [70, 90, 110], [30, 40, 50]],
  melancholic: [[70, 90, 170], [130, 110, 200], [180, 200, 230], [30, 40, 80], [15, 15, 35]],
};

/* ---------- 색 유틸 ---------- */
const hex = ([r, g, b]) => '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
const rgba = ([r, g, b], a = 1) => `rgba(${r | 0},${g | 0},${b | 0},${a})`;
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const lum = ([r, g, b]) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
const sat = ([r, g, b]) => { const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return mx ? (mx - mn) / mx : 0; };
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** 이미지에서 대표색 5개 추출 (k-means) */
export function extractPalette(img, k = 5) {
  const S = 56;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, S, S);
  const d = ctx.getImageData(0, 0, S, S).data;
  const px = [];
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200) px.push([d[i], d[i + 1], d[i + 2]]);
  if (!px.length) return null;

  // k-means++ 비슷한 초기화: 서로 먼 색부터
  const cents = [px[Math.floor(px.length / 2)]];
  while (cents.length < k) {
    let best = px[0], bd = -1;
    for (let i = 0; i < px.length; i += 7) {
      const md = Math.min(...cents.map((c2) => dist(px[i], c2)));
      if (md > bd) { bd = md; best = px[i]; }
    }
    cents.push(best);
  }
  let counts = new Array(k).fill(0);
  for (let it = 0; it < 10; it++) {
    const sums = cents.map(() => [0, 0, 0]);
    counts = new Array(k).fill(0);
    for (const p of px) {
      let bi = 0, bd = Infinity;
      for (let j = 0; j < k; j++) { const dd = dist(p, cents[j]); if (dd < bd) { bd = dd; bi = j; } }
      sums[bi][0] += p[0]; sums[bi][1] += p[1]; sums[bi][2] += p[2]; counts[bi]++;
    }
    for (let j = 0; j < k; j++) if (counts[j]) cents[j] = sums[j].map((v) => v / counts[j]);
  }
  return cents
    .map((c2, i) => ({ c: c2, n: counts[i] }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n)
    .map((x) => x.c);
}

export function paletteFor(img, moodId) {
  let p = null;
  try { p = img ? extractPalette(img) : null; } catch { p = null; } // CORS 오염 등
  if (!p || p.length < 3) p = MOOD_FALLBACK[moodId] || MOOD_FALLBACK.warm;
  while (p.length < 5) p.push(mix(p[0], [255, 255, 255], 0.5));
  // 강조색: 채도가 높고 너무 어둡지 않은 색
  const accent = [...p].sort((a, b) => sat(b) * (0.3 + lum(b)) - sat(a) * (0.3 + lum(a)))[0];
  return { colors: p, accent: lum(accent) < 0.35 ? mix(accent, [255, 255, 255], 0.45) : accent, hex: p.map(hex) };
}

/* ---------- 그리기 ---------- */
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function fitText(ctx, text, maxW, size, weight = 800) {
  let s = size;
  do { ctx.font = `${weight} ${s}px ${FONT}`; s -= 2; } while (ctx.measureText(text).width > maxW && s > 28);
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '…').width > maxW) t = t.slice(0, -1);
  return t + '…';
}

function drawRadar(ctx, cx, cy, r, features, accent) {
  const n = AXES.length;
  const pt = (i, v) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    return [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
  };
  ctx.lineWidth = 2;
  for (const ring of [0.25, 0.5, 0.75, 1]) {
    ctx.beginPath();
    for (let i = 0; i <= n; i++) { const [x, y] = pt(i % n, ring); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.strokeStyle = `rgba(255,255,255,${ring === 1 ? 0.28 : 0.12})`;
    ctx.stroke();
  }
  for (let i = 0; i < n; i++) {
    const [x, y] = pt(i, 1);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y);
    ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.stroke();
  }
  ctx.beginPath();
  AXES.forEach(([k], i) => { const [x, y] = pt(i, Math.max(0.06, features[k] / 100)); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.closePath();
  ctx.fillStyle = rgba(accent, 0.38); ctx.fill();
  ctx.lineWidth = 5; ctx.strokeStyle = rgba(accent, 1); ctx.stroke();
  AXES.forEach(([k], i) => {
    const [x, y] = pt(i, Math.max(0.06, features[k] / 100));
    ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
  });
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  AXES.forEach(([k, label], i) => {
    const [x, y] = pt(i, 1.24);
    ctx.font = `600 30px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.75)'; ctx.fillText(label, x, y - 18);
    ctx.font = `800 34px ${FONT}`; ctx.fillStyle = '#fff'; ctx.fillText(String(features[k]), x, y + 20);
  });
}

/** 카드 렌더링. meta: {title, artist, album, year}, a: analyzeSamples 결과 */
export function renderCard(canvas, { meta, a, palette, artwork }) {
  const W = 1080, H = 1920;
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  const [c0, c1, c2] = palette.colors;
  const accent = palette.accent;

  // 배경: 대표색을 어둡게 깐 그라디언트 + 빛 번짐
  const bg = ctx.createLinearGradient(0, 0, W * 0.3, H);
  bg.addColorStop(0, rgba(mix(c0, [8, 8, 14], 0.55)));
  bg.addColorStop(0.55, rgba(mix(c1, [8, 8, 14], 0.72)));
  bg.addColorStop(1, rgba(mix(c2, [5, 5, 10], 0.85)));
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  for (const [x, y, r, col, al] of [[W * 0.85, 260, 520, accent, 0.35], [W * 0.1, H * 0.62, 600, c1, 0.28]]) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, rgba(col, al)); g.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }

  const PAD = 84;
  ctx.textBaseline = 'alphabetic';
  // 헤더
  ctx.textAlign = 'left'; ctx.font = `800 30px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.fillText('SONG DNA', PAD, 112);
  ctx.textAlign = 'right'; ctx.font = `600 28px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.fillText(meta.year ? `${meta.year} · ${fmtTime(meta.durationSec || a.duration)}` : fmtTime(meta.durationSec || a.duration), W - PAD, 112);

  // 앨범아트
  const AS = 500, ax = (W - AS) / 2, ay = 160;
  ctx.save();
  ctx.shadowColor = 'rgba(0,0,0,0.55)'; ctx.shadowBlur = 70; ctx.shadowOffsetY = 30;
  roundRect(ctx, ax, ay, AS, AS, 36); ctx.fillStyle = rgba(c0); ctx.fill();
  ctx.restore();
  ctx.save(); roundRect(ctx, ax, ay, AS, AS, 36); ctx.clip();
  if (artwork) ctx.drawImage(artwork, ax, ay, AS, AS);
  else {
    const g = ctx.createLinearGradient(ax, ay, ax + AS, ay + AS);
    palette.colors.forEach((c, i) => g.addColorStop(i / (palette.colors.length - 1), rgba(c)));
    ctx.fillStyle = g; ctx.fillRect(ax, ay, AS, AS);
    ctx.font = `900 220px ${FONT}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText('♪', W / 2, ay + AS / 2);
  }
  ctx.restore();

  // 제목/아티스트
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic'; ctx.fillStyle = '#fff';
  const title = fitText(ctx, meta.title || '제목 없음', W - PAD * 2, 76);
  ctx.fillText(title, W / 2, ay + AS + 100);
  ctx.font = `600 38px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.75)';
  ctx.fillText(fitText(ctx, meta.artist || '알 수 없는 아티스트', W - PAD * 2, 38, 600), W / 2, ay + AS + 152);

  // 분위기 pill
  const moodText = `${a.mood.ko}  ·  ${a.mood.en.toUpperCase()}`;
  ctx.font = `800 32px ${FONT}`;
  const mw = ctx.measureText(moodText).width + 64, my = ay + AS + 186;
  roundRect(ctx, (W - mw) / 2, my, mw, 64, 32); ctx.fillStyle = rgba(accent, 0.95); ctx.fill();
  ctx.fillStyle = lum(accent) > 0.6 ? '#14121c' : '#fff'; ctx.textBaseline = 'middle';
  ctx.fillText(moodText, W / 2, my + 33);

  // 지표 타일
  const tiles = [['BPM', String(Math.round(a.bpm))], ['KEY', a.key.name], ['CAMELOT', a.key.camelot]];
  const ty = my + 100, tw = (W - PAD * 2 - 40) / 3, th = 140;
  tiles.forEach(([label, val], i) => {
    const tx = PAD + i * (tw + 20);
    roundRect(ctx, tx, ty, tw, th, 28); ctx.fillStyle = 'rgba(255,255,255,0.09)'; ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.14)'; ctx.lineWidth = 2; ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    ctx.font = `700 26px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.6)'; ctx.fillText(label, tx + tw / 2, ty + 46);
    ctx.font = `900 64px ${FONT}`; ctx.fillStyle = '#fff'; ctx.fillText(val, tx + tw / 2, ty + 114);
  });

  // 레이더
  drawRadar(ctx, W / 2, ty + th + 248, 158, a.features, accent);

  // 에너지 타임라인
  const ey = ty + th + 548, eh = 108, ex = PAD, ew = W - PAD * 2;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'; ctx.font = `700 26px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.fillText('ENERGY FLOW', ex, ey - 22);
  ctx.textAlign = 'right'; ctx.fillText(`PEAK ${fmtTime(a.peakSec)}`, ex + ew, ey - 22);
  const n = a.curve.length, bw = ew / n;
  const grad = ctx.createLinearGradient(ex, 0, ex + ew, 0);
  grad.addColorStop(0, rgba(mix(accent, [255, 255, 255], 0.35))); grad.addColorStop(1, rgba(accent));
  ctx.fillStyle = grad;
  a.curve.forEach((v, i) => {
    const h = Math.max(6, v * eh);
    roundRect(ctx, ex + i * bw + 2, ey + (eh - h) / 2, Math.max(2, bw - 4), h, Math.min(4, (bw - 4) / 2)); ctx.fill();
  });
  ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.setLineDash([6, 8]); ctx.lineWidth = 2;
  for (const b of a.boundaries) { const x = ex + (b / a.duration) * ew; ctx.beginPath(); ctx.moveTo(x, ey - 4); ctx.lineTo(x, ey + eh + 4); ctx.stroke(); }
  ctx.setLineDash([]);

  // 팔레트
  const py = ey + eh + 40, sw = (W - PAD * 2 - 4 * 16) / 5;
  palette.colors.slice(0, 5).forEach((c, i) => {
    const sx = PAD + i * (sw + 16);
    roundRect(ctx, sx, py, sw, 58, 16); ctx.fillStyle = rgba(c); ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 2; ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = `700 20px ${FONT}`;
    ctx.fillStyle = lum(c) > 0.55 ? 'rgba(0,0,0,0.65)' : 'rgba(255,255,255,0.8)';
    ctx.fillText(hex(c).toUpperCase(), sx + sw / 2, py + 29);
    ctx.textBaseline = 'alphabetic';
  });

  ctx.textAlign = 'center'; ctx.font = `600 24px ${FONT}`; ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.fillText(meta.isPreview ? '30초 미리듣기 기반 분석 · Song DNA' : 'Song DNA', W / 2, H - 50);
}
