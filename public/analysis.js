// 브라우저/Node 공용 오디오 분석 엔진 (외부 라이브러리 없음)
// 입력: 모노 PCM(Float32Array) + 샘플레이트
// 출력: BPM, 키, 캠롯, 에너지 곡선, 구간 경계, 0~100 특징 점수, 분위기

export const SR = 22050;
const NOTES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
const NOTES_KO = { major: '장조', minor: '단조' };

// Krumhansl–Kessler 조성 프로파일
const MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
const MINOR = [6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];

/* ---------- 기본 DSP ---------- */

function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci;
        const ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
        const nr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr; cr = nr;
      }
    }
  }
}

const hannCache = new Map();
function hann(n) {
  if (!hannCache.has(n)) {
    const w = new Float32Array(n);
    for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));
    hannCache.set(n, w);
  }
  return hannCache.get(n);
}

/** 프레임별 크기 스펙트럼을 콜백으로 전달 */
function stft(x, n, hop, onFrame) {
  const w = hann(n);
  const re = new Float32Array(n), im = new Float32Array(n), mag = new Float32Array(n / 2);
  const frames = Math.max(1, Math.floor((x.length - n) / hop) + 1);
  for (let f = 0; f < frames; f++) {
    const off = f * hop;
    for (let i = 0; i < n; i++) { re[i] = (x[off + i] || 0) * w[i]; im[i] = 0; }
    fft(re, im);
    for (let k = 0; k < n / 2; k++) mag[k] = Math.hypot(re[k], im[k]);
    onFrame(mag, f);
  }
  return frames;
}

const clamp = (v, a = 0, b = 100) => Math.min(b, Math.max(a, v));
const scale = (v, lo, hi) => clamp(((v - lo) / (hi - lo)) * 100);
const mean = (a) => a.reduce((s, v) => s + v, 0) / (a.length || 1);
function percentile(arr, p) {
  const s = Array.from(arr).sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.round((p / 100) * (s.length - 1))))];
}
function pearson(a, b) {
  const ma = mean(a), mb = mean(b);
  let n = 0, da = 0, db = 0;
  for (let i = 0; i < a.length; i++) {
    n += (a[i] - ma) * (b[i] - mb); da += (a[i] - ma) ** 2; db += (b[i] - mb) ** 2;
  }
  return n / Math.sqrt(da * db || 1);
}

/* ---------- 템포 ---------- */

function estimateTempo(x, sr) {
  const n = 1024, hop = 256, fps = sr / hop;
  const onset = [];
  let prev = null;
  stft(x, n, hop, (mag) => {
    const lm = new Float32Array(mag.length);
    let flux = 0;
    for (let k = 1; k < mag.length; k++) {
      lm[k] = Math.log1p(100 * mag[k]);
      if (prev) flux += Math.max(0, lm[k] - prev[k]);
    }
    onset.push(flux);
    prev = lm;
  });

  // 국소 평균 제거 + 반파 정류
  const win = Math.round(fps * 0.5);
  const o = onset.map((v, i) => {
    let s = 0, c = 0;
    for (let j = Math.max(0, i - win); j <= Math.min(onset.length - 1, i + win); j++) { s += onset[j]; c++; }
    return Math.max(0, v - s / c);
  });

  const minLag = Math.floor((60 * fps) / 210), maxLag = Math.ceil((60 * fps) / 55);
  const ac = new Float32Array(maxLag + 2);
  for (let lag = 0; lag <= maxLag + 1; lag++) {
    let s = 0;
    for (let i = 0; i + lag < o.length; i++) s += o[i] * o[i + lag];
    ac[lag] = s / (o.length - lag || 1);
  }

  let best = minLag, bestScore = -Infinity;
  for (let lag = minLag; lag <= maxLag; lag++) {
    const bpm = (60 * fps) / lag;
    const prior = Math.exp(-0.5 * (Math.log2(bpm / 120) / 0.9) ** 2); // 120BPM 근방 선호
    const harm = ac[lag] + 0.5 * (ac[lag * 2] || 0); // 배박 일치도 가산
    const score = harm * prior;
    if (score > bestScore) { bestScore = score; best = lag; }
  }
  // 포물선 보간으로 소수점 BPM
  const y0 = ac[best - 1], y1 = ac[best], y2 = ac[best + 1];
  const d = (y0 - y2) / (2 * (y0 - 2 * y1 + y2) || 1);
  const lag = best + (Math.abs(d) < 1 ? d : 0);
  const bpm = (60 * fps) / lag;

  return {
    bpm: Math.round(bpm * 10) / 10,
    pulseClarity: ac[0] ? clamp(ac[best] / ac[0], 0, 1) : 0,
    onsetDensity: mean(onset),
  };
}

/* ---------- 키(조성) ---------- */

function estimateKey(x, sr) {
  const n = 4096, hop = 2048;
  const chroma = new Float64Array(12);
  const binPc = new Int8Array(n / 2).fill(-1);
  for (let k = 1; k < n / 2; k++) {
    const f = (k * sr) / n;
    if (f < 65 || f > 4200) continue;
    binPc[k] = ((Math.round(69 + 12 * Math.log2(f / 440)) % 12) + 12) % 12;
  }
  const frameChroma = [];
  stft(x, n, hop, (mag) => {
    const c = new Float64Array(12);
    for (let k = 1; k < mag.length; k++) if (binPc[k] >= 0) c[binPc[k]] += Math.log1p(10 * mag[k]);
    for (let i = 0; i < 12; i++) chroma[i] += c[i];
    frameChroma.push(c);
  });

  const scores = [];
  for (let tonic = 0; tonic < 12; tonic++) {
    const rot = Array.from({ length: 12 }, (_, i) => chroma[(i + tonic) % 12]);
    scores.push({ tonic, mode: 'major', r: pearson(rot, MAJOR) });
    scores.push({ tonic, mode: 'minor', r: pearson(rot, MINOR) });
  }
  scores.sort((a, b) => b.r - a.r);
  const top = scores[0];
  const max = Math.max(...chroma);
  return {
    tonic: top.tonic,
    mode: top.mode,
    name: `${NOTES[top.tonic]}${top.mode === 'minor' ? 'm' : ''}`,
    label: `${NOTES[top.tonic]} ${NOTES_KO[top.mode]}`,
    camelot: camelot(top.tonic, top.mode),
    confidence: clamp((top.r - scores[1].r) * 4 + top.r * 0.6, 0, 1),
    alternatives: scores.slice(1, 3).map((s) => `${NOTES[s.tonic]}${s.mode === 'minor' ? 'm' : ''}`),
    chroma: Array.from(chroma, (v) => (max ? v / max : 0)),
    frameChroma,
    chromaFps: sr / hop,
  };
}

export function camelot(pc, mode) {
  const num = (((pc * 7) % 12) + (mode === 'major' ? 7 : 4)) % 12 + 1;
  return `${num}${mode === 'major' ? 'B' : 'A'}`;
}

/** 캠롯 휠에서 자연스럽게 믹싱되는 키 */
export function camelotNeighbors(code) {
  const num = parseInt(code, 10), letter = code.slice(-1);
  const wrap = (v) => ((v - 1 + 12) % 12) + 1;
  return [
    { code, why: '같은 키' },
    { code: `${wrap(num + 1)}${letter}`, why: '한 칸 위 (에너지 상승)' },
    { code: `${wrap(num - 1)}${letter}`, why: '한 칸 아래 (차분하게)' },
    { code: `${num}${letter === 'A' ? 'B' : 'A'}`, why: letter === 'A' ? '나란한조 장조 (밝게)' : '나란한조 단조 (어둡게)' },
  ];
}

/* ---------- 에너지 · 음색 · 구간 ---------- */

function energyAndTimbre(x, sr) {
  const n = 2048, hop = 1024;
  const rms = [], centroid = [], flat = [];
  stft(x, n, hop, (mag, f) => {
    let e = 0, num = 0, den = 0, logSum = 0, lin = 0;
    for (let i = 0; i < n; i++) { const s = x[f * hop + i] || 0; e += s * s; }
    for (let k = 1; k < mag.length; k++) {
      const m = mag[k];
      num += ((k * sr) / n) * m; den += m;
      logSum += Math.log(m + 1e-10); lin += m;
    }
    rms.push(Math.sqrt(e / n));
    centroid.push(den ? num / den : 0);
    flat.push(lin ? Math.exp(logSum / (mag.length - 1)) / (lin / (mag.length - 1)) : 0);
  });
  return { rms, centroid, flat, fps: sr / hop };
}

/** 에너지 곡선을 bins개 막대로 요약 (0~1) */
function summarizeCurve(rms, bins) {
  const out = [];
  const per = rms.length / bins;
  for (let b = 0; b < bins; b++) {
    const seg = rms.slice(Math.floor(b * per), Math.max(Math.floor(b * per) + 1, Math.floor((b + 1) * per)));
    out.push(Math.sqrt(mean(seg.map((v) => v * v))));
  }
  const max = Math.max(...out) || 1;
  return out.map((v) => v / max);
}

/** 크로마+에너지 자기유사도에서 체커보드 커널로 구간 경계 찾기 */
function segment(frameChroma, chromaFps, rms, rmsFps, duration) {
  const step = duration > 60 ? 1 : 0.5; // 초 단위 블록
  const blocks = Math.floor(duration / step);
  if (blocks < 8) return [];
  const feats = [];
  for (let b = 0; b < blocks; b++) {
    const c = new Float64Array(13);
    const c0 = Math.floor(b * step * chromaFps), c1 = Math.max(c0 + 1, Math.floor((b + 1) * step * chromaFps));
    for (let f = c0; f < Math.min(c1, frameChroma.length); f++) for (let i = 0; i < 12; i++) c[i] += frameChroma[f][i];
    const r0 = Math.floor(b * step * rmsFps), r1 = Math.floor((b + 1) * step * rmsFps);
    const r = mean(rms.slice(r0, r1));
    const norm = Math.hypot(...c.slice(0, 12)) || 1;
    for (let i = 0; i < 12; i++) c[i] /= norm;
    c[12] = 3 * Math.log10(1 + 50 * r); // 에너지 변화도 경계 단서로 사용
    feats.push(c);
  }
  const sim = (a, b) => { let s = 0; for (let i = 0; i < 13; i++) s += (a[i] - b[i]) ** 2; return -Math.sqrt(s); };
  const L = Math.max(3, Math.round((duration > 60 ? 8 : 3) / step));
  const nov = new Float64Array(blocks);
  for (let t = L; t < blocks - L; t++) {
    let s = 0;
    for (let i = -L; i < L; i++) for (let j = -L; j < L; j++) {
      const sign = (i < 0) === (j < 0) ? 1 : -1;
      s += sign * sim(feats[t + i], feats[t + j]);
    }
    nov[t] = s;
  }
  const thr = mean(nov) + 0.5 * Math.sqrt(mean(Array.from(nov, (v) => (v - mean(nov)) ** 2)));
  const minGap = Math.round((duration > 60 ? 12 : 5) / step);
  const peaks = [];
  for (let t = 1; t < blocks - 1; t++) {
    if (nov[t] > thr && nov[t] >= nov[t - 1] && nov[t] >= nov[t + 1]) peaks.push({ t, v: nov[t] });
  }
  peaks.sort((a, b) => b.v - a.v);
  const chosen = [];
  for (const p of peaks) if (chosen.every((c) => Math.abs(c - p.t) >= minGap)) chosen.push(p.t);
  return chosen.slice(0, duration > 60 ? 8 : 3).sort((a, b) => a - b).map((t) => +(t * step).toFixed(1));
}

/* ---------- 종합 ---------- */

const MOODS = {
  euphoric: { ko: '신나는 · 축제', en: 'Euphoric', desc: '빠르고 밝은 에너지로 분위기를 끌어올리는 곡' },
  intense: { ko: '강렬한 · 긴장감', en: 'Intense', desc: '어둡고 힘 있는 사운드가 몰아치는 곡' },
  warm: { ko: '따뜻한 · 여유', en: 'Warm', desc: '편안하고 밝은 톤으로 감싸 주는 곡' },
  melancholic: { ko: '애잔한 · 몽환', en: 'Melancholic', desc: '차분하고 어두운 감정선이 흐르는 곡' },
};

export function analyzeSamples(x, sr = SR) {
  const duration = x.length / sr;
  if (duration < 3) throw new Error('분석하기에 너무 짧은 오디오예요 (3초 이상 필요).');

  const tempo = estimateTempo(x, sr);
  const key = estimateKey(x, sr);
  const et = energyAndTimbre(x, sr);

  const db = et.rms.map((v) => 20 * Math.log10(v + 1e-9));
  const loudDb = 20 * Math.log10(Math.sqrt(mean(et.rms.map((v) => v * v))) + 1e-9);
  const voiced = db.filter((v) => v > -60);
  const dynRange = voiced.length ? percentile(voiced, 95) - percentile(voiced, 10) : 0;
  const centroidHz = mean(et.centroid.filter((_, i) => db[i] > -50)) || mean(et.centroid);
  const flatness = mean(et.flat);

  const tempoNorm = scale(tempo.bpm, 60, 180);
  const brightness = scale(centroidHz, 700, 3200);
  const loudness = scale(loudDb, -32, -8);
  const flux = scale(Math.log10(1 + tempo.onsetDensity), 1.2, 2.6);
  const energy = clamp(0.55 * loudness + 0.3 * flux + 0.15 * tempoNorm);
  const tempoFit = Math.exp(-0.5 * ((tempo.bpm - 118) / 28) ** 2);
  const danceability = clamp(scale(tempo.pulseClarity, 0.05, 0.55) * (0.45 + 0.55 * tempoFit));
  const modeScore = key.mode === 'major' ? 50 + 50 * key.confidence : 50 - 50 * key.confidence;
  const valence = clamp(0.5 * modeScore + 0.3 * brightness + 0.2 * tempoNorm);
  const dynamics = scale(dynRange, 4, 24);
  const acoustic = clamp(100 - scale(flatness, 0.02, 0.25) * 0.6 - brightness * 0.4);

  const arousal = (energy + tempoNorm) / 2;
  const moodKey = arousal >= 50 ? (valence >= 50 ? 'euphoric' : 'intense') : valence >= 50 ? 'warm' : 'melancholic';

  const curve = summarizeCurve(et.rms, 64);
  const peakBin = curve.indexOf(Math.max(...curve));
  const boundaries = segment(key.frameChroma, key.chromaFps, et.rms, et.fps, duration);

  return {
    duration: +duration.toFixed(2),
    bpm: tempo.bpm,
    tempoLabel: tempo.bpm < 76 ? '느린 템포 (Slow)' : tempo.bpm < 108 ? '미디엄 템포 (Mid)' : tempo.bpm < 132 ? '업템포 (Up)' : '빠른 템포 (Fast)',
    pulseClarity: +tempo.pulseClarity.toFixed(3),
    key: { name: key.name, label: key.label, mode: key.mode, camelot: key.camelot, confidence: +key.confidence.toFixed(2), alternatives: key.alternatives },
    chroma: key.chroma,
    loudnessDb: +loudDb.toFixed(1),
    dynamicRangeDb: +dynRange.toFixed(1),
    centroidHz: Math.round(centroidHz),
    features: {
      energy: Math.round(energy),
      danceability: Math.round(danceability),
      valence: Math.round(valence),
      brightness: Math.round(brightness),
      tempo: Math.round(tempoNorm),
      dynamics: Math.round(dynamics),
      acoustic: Math.round(acoustic),
    },
    mood: { id: moodKey, ...MOODS[moodKey], arousal: Math.round(arousal), valence: Math.round(valence) },
    curve,
    peakSec: +(((peakBin + 0.5) / curve.length) * duration).toFixed(1),
    boundaries,
  };
}

/** 분석 결과 → 사람이 읽는 인사이트 문장 */
export function buildInsights(a, meta = {}) {
  const out = [];
  const f = a.features;
  out.push(`${a.bpm} BPM의 ${a.tempoLabel.split(' (')[0]} 곡이에요. ${a.pulseClarity > 0.3 ? '비트가 또렷해서 리듬을 타기 쉬워요.' : '비트가 부드럽게 흐르는 편이에요.'}`);
  out.push(`키는 ${a.key.label}(${a.key.name}, 캠롯 ${a.key.camelot})로 추정돼요${a.key.confidence < 0.35 ? ` — 다만 확신도가 낮아 ${a.key.alternatives[0]}일 가능성도 있어요` : ''}.`);
  out.push(`분위기는 "${a.mood.ko}" 쪽이에요. ${a.mood.desc}이에요.`);
  if (f.energy >= 70) out.push('에너지가 높아 운동·드라이브 플레이리스트에 잘 어울려요.');
  else if (f.energy <= 35) out.push('에너지가 낮고 잔잔해 공부·휴식용 배경음악으로 좋아요.');
  if (f.dynamics >= 60) out.push(`셈여림 폭이 넓어요(${a.dynamicRangeDb}dB). 조용한 부분과 터지는 부분의 대비가 커요.`);
  else if (f.dynamics <= 25) out.push(`셈여림 폭이 좁아요(${a.dynamicRangeDb}dB). 처음부터 끝까지 꽉 찬 사운드로 압축된 마스터링이에요.`);
  out.push(`가장 에너지가 높은 지점은 ${fmtTime(a.peakSec)} 부근이에요${meta.isPreview ? ' (미리듣기 구간 기준)' : ''}.`);
  if (meta.deezerBpm && Math.abs(meta.deezerBpm - a.bpm) > 4) {
    const ratio = meta.deezerBpm / a.bpm;
    out.push(Math.abs(ratio - 2) < 0.1 || Math.abs(ratio - 0.5) < 0.05
      ? `Deezer 데이터베이스 BPM(${meta.deezerBpm})과 2배 관계예요. 하프타임/더블타임 해석 차이예요.`
      : `참고: Deezer 데이터베이스 BPM은 ${meta.deezerBpm}이에요.`);
  }
  return out;
}

export const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/* ---------- 브라우저 전용: 디코딩 ---------- */

export async function decodeToMono(arrayBuffer, maxSeconds = 240) {
  const AC = globalThis.AudioContext || globalThis.webkitAudioContext;
  const ctx = new AC();
  const decoded = await ctx.decodeAudioData(arrayBuffer);
  ctx.close();
  const dur = Math.min(decoded.duration, maxSeconds);
  const off = new OfflineAudioContext(1, Math.ceil(dur * SR), SR);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  return { samples: rendered.getChannelData(0), truncated: decoded.duration > maxSeconds, fullDuration: decoded.duration };
}
