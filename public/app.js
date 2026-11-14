import { analyzeSamples, buildInsights, camelotNeighbors, decodeToMono, fmtTime } from './analysis.js';
import { AXES, paletteFor, renderCard } from './card.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const media = (url) => `/api/media?url=${encodeURIComponent(url)}`;
const NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
const FEATURE_LABELS = { ...Object.fromEntries(AXES), acoustic: '어쿠스틱' };
const ROLE_KO = { Main: '메인 아티스트', Featured: '피처링' };

let current = null; // { meta, analysis, palette }

/* ---------- 진행 상태 ---------- */
function step(name, msg) {
  $('#status').hidden = false;
  const order = ['resolve', 'audio', 'analyze', 'render'];
  const idx = order.indexOf(name);
  document.querySelectorAll('.steps li').forEach((li) => {
    const i = order.indexOf(li.dataset.step);
    li.className = i < idx ? 'done' : i === idx ? 'active' : '';
  });
  const m = $('#statusMsg');
  m.className = 'msg';
  m.textContent = msg || '';
}
function done() {
  document.querySelectorAll('.steps li').forEach((li) => (li.className = 'done'));
  $('#statusMsg').textContent = '';
}
function fail(err) {
  document.querySelectorAll('.steps li.active').forEach((li) => (li.className = ''));
  const m = $('#statusMsg');
  m.className = 'msg error';
  m.textContent = err.message || String(err);
  setBusy(false);
}
function setBusy(b) {
  $('#go').disabled = b;
  $('#go').textContent = b ? '분석 중…' : '분석하기';
}

/* ---------- 로딩 헬퍼 ---------- */
function loadImage(src) {
  return new Promise((ok) => {
    if (!src) return ok(null);
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => ok(img);
    img.onerror = () => ok(null);
    img.src = src;
  });
}

async function fetchJson(url) {
  let res;
  try {
    res = await fetch(url);
  } catch {
    throw new Error('서버에 연결할 수 없어요. `npm start`로 서버를 실행했는지 확인해 주세요.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}

/* ---------- 메인 흐름 ---------- */
async function analyzeLink(q) {
  setBusy(true);
  try {
    step('resolve', '플랫폼에서 곡 정보를 찾고 있어요…');
    const { track, detected } = await fetchJson(`/api/resolve?q=${encodeURIComponent(q)}`);
    if (!track.preview) throw new Error(`"${track.title}"은(는) 미리듣기 음원이 없어 분석할 수 없어요. 음악 파일을 직접 올려 보세요.`);

    step('audio', `"${track.artist} – ${track.title}" 미리듣기를 받는 중…`);
    const res = await fetch(media(track.preview));
    if (!res.ok) throw new Error('미리듣기 음원을 받지 못했어요.');
    const buf = await res.arrayBuffer();

    const meta = {
      title: track.title,
      artist: track.artist,
      album: track.album,
      year: track.releaseDate?.slice(0, 4),
      releaseDate: track.releaseDate,
      durationSec: track.durationSec,
      genres: track.genres,
      label: track.label,
      isrc: track.isrc,
      deezerBpm: track.bpm,
      gainDb: track.gainDb,
      explicit: track.explicit,
      contributors: track.contributors,
      links: track.links,
      detected,
      isPreview: true,
      previewUrl: media(track.preview),
      artworkUrl: track.artwork ? media(track.artwork) : null,
    };
    await runAnalysis(buf, meta);
  } catch (e) {
    fail(e);
  }
}

async function analyzeFile(file) {
  setBusy(true);
  try {
    step('audio', `"${file.name}" 읽는 중…`);
    const buf = await file.arrayBuffer();
    const base = file.name.replace(/\.[^.]+$/, '');
    const [artist, title] = base.includes(' - ') ? base.split(' - ', 2) : ['', base];
    await runAnalysis(buf, {
      title: title.trim(),
      artist: artist.trim() || '내 파일',
      isPreview: false,
      previewUrl: URL.createObjectURL(file),
      contributors: [],
      links: {},
      fileName: file.name,
    });
  } catch (e) {
    fail(e);
  }
}

async function runAnalysis(buf, meta) {
  step('analyze', '템포 · 키 · 에너지 · 음색을 계산하고 있어요…');
  await new Promise((r) => setTimeout(r, 30)); // UI 갱신 틈
  let decoded;
  try {
    decoded = await decodeToMono(buf);
  } catch {
    throw new Error('오디오를 디코딩하지 못했어요. 다른 파일 형식으로 시도해 보세요.');
  }
  const t0 = performance.now();
  const analysis = analyzeSamples(decoded.samples);
  analysis.ms = Math.round(performance.now() - t0);
  if (!meta.durationSec) meta.durationSec = Math.round(decoded.fullDuration);
  meta.truncated = decoded.truncated;

  step('render', 'Song DNA 카드를 그리고 있어요…');
  const artwork = await loadImage(meta.artworkUrl);
  const palette = paletteFor(artwork, analysis.mood.id);
  renderCard($('#card'), { meta, a: analysis, palette, artwork });

  current = { meta, analysis, palette };
  renderPanels(meta, analysis, palette);
  done();
  setBusy(false);
  $('#result').hidden = false;
  $('#result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- 상세 패널 ---------- */
function renderPanels(meta, a, palette) {
  const accent = `rgb(${palette.accent.map((v) => v | 0).join(',')})`;
  document.documentElement.style.setProperty('--accent', accent);

  const rows = [
    ['곡', meta.title],
    ['아티스트', meta.artist],
    ['앨범', meta.album],
    ['발매일', meta.releaseDate],
    ['장르', meta.genres?.join(', ')],
    ['레이블', meta.label],
    ['길이', meta.durationSec && fmtTime(meta.durationSec)],
    ['ISRC', meta.isrc],
    ['분석 구간', meta.isPreview ? `미리듣기 ${Math.round(a.duration)}초` : `${fmtTime(a.duration)}${meta.truncated ? ' (앞부분만)' : ''}`],
  ].filter(([, v]) => v);
  $('#meta').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
  const LINK_NAMES = { spotify: 'Spotify', youtube: 'YouTube', apple: 'Apple Music', deezer: 'Deezer' };
  $('#links').innerHTML = Object.entries(meta.links || {})
    .filter(([, u]) => u)
    .map(([k, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${LINK_NAMES[k] || k} ↗</a>`)
    .join('');

  const stats = [
    [`${a.bpm}`, `BPM · ${a.tempoLabel}`],
    [a.key.name, `${a.key.label} · 확신도 ${Math.round(a.key.confidence * 100)}%`],
    [a.key.camelot, '캠롯 키'],
    [`${a.loudnessDb} dB`, `평균 음량 · 다이내믹 ${a.dynamicRangeDb}dB`],
  ];
  $('#stats').innerHTML = stats.map(([b, s]) => `<div class="stat"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join('');

  $('#insights').innerHTML = buildInsights(a, meta).map((t) => `<li>${esc(t)}</li>`).join('');

  $('#features').innerHTML = Object.entries(a.features)
    .map(([k, v]) => `<div class="feat"><span>${FEATURE_LABELS[k] || k}</span><div class="bar"><i style="width:0%" data-w="${v}"></i></div><em>${v}</em></div>`)
    .join('');
  requestAnimationFrame(() => document.querySelectorAll('.feat i').forEach((i) => (i.style.width = `${i.dataset.w}%`)));

  $('#flowNote').textContent = `최고점 ${fmtTime(a.peakSec)}` + (a.boundaries.length ? ` · 점선 = 전개가 바뀌는 지점 ${a.boundaries.length}곳` : '');
  $('#flow').innerHTML = flowSvg(a);
  $('#chroma').innerHTML = chromaSvg(a);

  const lo = Math.round(a.bpm * 0.94), hi = Math.round(a.bpm * 1.06);
  $('#mix').innerHTML = `
    <div class="wheel">${camelotNeighbors(a.key.camelot).map((n) => `<div class="code"><b>${n.code}</b><span>${n.why}</span></div>`).join('')}</div>
    <p>템포 ${lo}–${hi} BPM(±6%) 곡과 피치 변화 없이 자연스럽게 이어져요. 하프/더블타임으로는 ${Math.round(a.bpm / 2)} · ${Math.round(a.bpm * 2)} BPM도 가능해요.</p>`;

  const credits = meta.contributors || [];
  $('#creditsPanel').hidden = !credits.length;
  $('#credits').innerHTML = credits.map((c) => `<li>${esc(c.name)}<span>${esc(ROLE_KO[c.role] || c.role || '')}</span></li>`).join('');

  $('#player').src = meta.previewUrl || '';
}

function flowSvg(a) {
  const W = 720, H = 140, n = a.curve.length, bw = W / n;
  const bars = a.curve
    .map((v, i) => {
      const h = Math.max(3, v * (H - 30));
      return `<rect x="${(i * bw + 1).toFixed(1)}" y="${(H - 20 - h).toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="var(--accent)" opacity="${(0.45 + v * 0.55).toFixed(2)}"/>`;
    })
    .join('');
  const lines = a.boundaries
    .map((b) => { const x = (b / a.duration) * W; return `<line x1="${x}" x2="${x}" y1="4" y2="${H - 20}" stroke="currentColor" stroke-dasharray="4 4" opacity=".5"/><text x="${x + 4}" y="14">${fmtTime(b)}</text>`; })
    .join('');
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => `<text x="${t * W}" y="${H - 4}" text-anchor="${t === 0 ? 'start' : t === 1 ? 'end' : 'middle'}">${fmtTime(t * a.duration)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="시간에 따른 에너지 변화" style="color:var(--text)">${bars}${lines}${ticks}</svg>`;
}

function chromaSvg(a) {
  const W = 360, H = 130, bw = W / 12;
  const tonic = NOTE_NAMES.indexOf(a.key.name.replace('m', ''));
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="12음 분포">${a.chroma
    .map((v, i) => {
      const h = Math.max(2, v * (H - 24));
      return `<rect x="${i * bw + 3}" y="${H - 18 - h}" width="${bw - 6}" height="${h}" rx="3" fill="var(--accent)" opacity="${i === tonic ? 1 : 0.4}"/><text x="${i * bw + bw / 2}" y="${H - 4}" text-anchor="middle">${NOTE_NAMES[i]}</text>`;
    })
    .join('')}</svg>`;
}

/* ---------- 저장 · 공유 ---------- */
const fileName = () => `song-dna-${(current?.meta.title || 'card').replace(/[^\p{L}\p{N}]+/gu, '-').slice(0, 40)}.png`;

$('#download').addEventListener('click', () => {
  $('#card').toBlob((blob) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fileName();
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, 'image/png');
});

$('#share').addEventListener('click', () => {
  $('#card').toBlob(async (blob) => {
    const file = new File([blob], fileName(), { type: 'image/png' });
    const text = `${current.meta.artist} – ${current.meta.title} | ${current.analysis.bpm} BPM · ${current.analysis.key.name} · ${current.analysis.mood.ko}`;
    if (navigator.canShare?.({ files: [file] })) {
      try { await navigator.share({ files: [file], title: 'Song DNA', text }); } catch { /* 사용자가 취소 */ }
    } else {
      await navigator.clipboard?.writeText(text);
      $('#share').textContent = '요약 복사됨 ✓';
      setTimeout(() => ($('#share').textContent = '공유하기'), 1800);
    }
  }, 'image/png');
});

/* ---------- 입력 ---------- */
$('#form').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = $('#q').value.trim();
  if (q) analyzeLink(q);
});
$('#examples').addEventListener('click', (e) => {
  if (e.target.tagName !== 'BUTTON') return;
  $('#q').value = e.target.textContent;
  analyzeLink(e.target.textContent);
});
$('#file').addEventListener('change', (e) => e.target.files[0] && analyzeFile(e.target.files[0]));
const drop = $('#drop');
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) analyzeFile(f); });

// ?q= 로 바로 분석 (공유 링크용)
const initial = new URLSearchParams(location.search).get('q');
if (initial) { $('#q').value = initial; analyzeLink(initial); }
