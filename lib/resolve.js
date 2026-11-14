// 링크 → 곡 메타데이터 해석기
// 지원: Spotify / YouTube / Apple Music / Deezer 링크, 또는 "아티스트 곡명" 검색어
// 외부 API 키 없이 동작하도록 공개 엔드포인트(Deezer, iTunes, oEmbed)만 사용한다.

const UA = 'Mozilla/5.0 (compatible; SongDNA/0.1)';
const SHORT_LINK_HOSTS = ['spotify.link', 'link.deezer.com', 'deezer.page.link', 'youtu.be'];

export class ResolveError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.status = status;
  }
}

/** 입력 문자열이 어떤 플랫폼의 어떤 리소스인지 판별 (네트워크 없이) */
export function parseInput(input) {
  const raw = String(input || '').trim();
  if (!raw) throw new ResolveError('링크나 검색어를 입력해 주세요.');

  let url;
  try {
    url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
    if (!url.hostname.includes('.') || /\s/.test(raw)) url = null;
  } catch {
    url = null;
  }
  if (!url) return { platform: 'search', query: raw };

  const host = url.hostname;
  const path = url.pathname;

  if (SHORT_LINK_HOSTS.includes(url.hostname) && url.hostname !== 'youtu.be') {
    return { platform: 'shortlink', url: url.href };
  }

  if (url.hostname.endsWith('spotify.com')) {
    const m = path.match(/\/(?:intl-[a-z-]+\/)?(track|album|playlist|artist|episode)\/([A-Za-z0-9]+)/);
    if (!m) throw new ResolveError('Spotify 링크 형식을 인식하지 못했어요.');
    return { platform: 'spotify', kind: m[1], id: m[2], url: `https://open.spotify.com/${m[1]}/${m[2]}` };
  }

  if (url.hostname === 'youtu.be') {
    return { platform: 'youtube', kind: 'track', id: path.slice(1).split('/')[0] };
  }
  if (url.hostname.endsWith('youtube.com')) {
    const id = url.searchParams.get('v') || (path.match(/\/(?:shorts|embed|live)\/([\w-]+)/) || [])[1];
    if (!id) throw new ResolveError('YouTube 영상 링크가 필요해요.');
    return { platform: 'youtube', kind: 'track', id };
  }

  if (url.hostname.endsWith('music.apple.com') || url.hostname.endsWith('itunes.apple.com')) {
    const country = (path.match(/^\/([a-z]{2})\//) || [])[1] || 'us';
    const songId = url.searchParams.get('i') || (path.match(/\/song\/[^/]*\/?(\d+)/) || [])[1];
    if (!songId) throw new ResolveError('Apple Music은 곡(트랙) 링크만 지원해요. 앨범 링크라면 곡을 선택해 공유해 주세요.');
    return { platform: 'apple', kind: 'track', id: songId, country };
  }

  if (host.endsWith('deezer.com')) {
    const m = path.match(/\/(track|album|playlist)\/(\d+)/);
    if (!m) throw new ResolveError('Deezer 링크 형식을 인식하지 못했어요.');
    return { platform: 'deezer', kind: m[1], id: m[2] };
  }

  throw new ResolveError(`아직 지원하지 않는 사이트예요: ${url.hostname}`);
}

/** 유튜브 영상 제목에서 검색에 방해되는 수식어를 걷어낸다 */
export function cleanVideoTitle(title, author = '') {
  let t = String(title)
    .replace(/[\[【][^\]】]*[\]】]/g, ' ')
    .replace(/\((?![^)]*\b(?:feat|ft|with)\b)[^)]*\)/gi, ' ')
    .replace(/\b(official|music|video|audio|lyrics?|visualizer|m\/?v|performance|teaser|4k|hd|hq)\b/gi, ' ')
    .replace(/[『』「」"“”‘’]|(^|\s)'|'(\s|$)/g, ' ')
    .replace(/\s*[|｜].*$/, '')
    .replace(/\s+/g, ' ')
    .trim();
  let artist = '';
  const dash = t.match(/^(.+?)\s+[-–—]\s+(.+)$/);
  if (dash) {
    artist = dash[1].trim();
    t = dash[2].trim();
  }
  if (!artist && / - Topic$/.test(author)) artist = author.replace(/ - Topic$/, '');
  return { artist, title: t, query: [artist, t].filter(Boolean).join(' ') };
}

/** Spotify 트랙 페이지 HTML에서 곡명/아티스트 추출 */
export function parseSpotifyHtml(html) {
  const meta = (prop) => {
    const re = new RegExp(`<meta[^>]+(?:property|name)="${prop}"[^>]+content="([^"]*)"`, 'i');
    return decodeEntities((html.match(re) || [])[1] || '');
  };
  const titleTag = decodeEntities((html.match(/<title>([^<]*)<\/title>/i) || [])[1] || '');
  let title = meta('og:title');
  let artist = '';
  const m = titleTag.match(/^(.*?) - (?:song|single|노래)(?: and lyrics)?(?: by| -) (.*?) \| Spotify/i);
  if (m) {
    title = title || m[1];
    artist = m[2];
  }
  if (!artist) {
    const desc = meta('og:description'); // 예: "BTS · Song · 2020"
    artist = desc.split(' · ')[0] || '';
  }
  return { title, artist, image: meta('og:image') };
}

function decodeEntities(s) {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

async function getJson(url) {
  const res = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'application/json' } });
  if (!res.ok) throw new ResolveError(`외부 API 오류 (${res.status}): ${new URL(url).hostname}`, 502);
  const data = await res.json();
  if (data && data.error) throw new ResolveError(`Deezer: ${data.error.message || '알 수 없는 오류'}`, 502);
  return data;
}

async function getText(url) {
  const res = await fetch(url, { headers: { 'User-Agent': UA, 'Accept-Language': 'en' } });
  if (!res.ok) throw new ResolveError(`페이지를 불러오지 못했어요 (${res.status})`, 502);
  return res.text();
}

/** Deezer 트랙 상세 + 앨범 장르 */
async function deezerTrack(id) {
  const t = await getJson(`https://api.deezer.com/track/${id}`);
  let album = null;
  try {
    album = await getJson(`https://api.deezer.com/album/${t.album.id}`);
  } catch {
    /* 장르 정보는 선택 사항 */
  }
  return {
    source: 'deezer',
    title: t.title,
    artist: t.artist?.name,
    album: t.album?.title,
    artwork: t.album?.cover_xl || t.album?.cover_big,
    artistImage: t.artist?.picture_xl,
    preview: t.preview || null,
    durationSec: t.duration,
    releaseDate: t.release_date || album?.release_date,
    isrc: t.isrc,
    bpm: t.bpm > 0 ? t.bpm : null,
    gainDb: typeof t.gain === 'number' ? t.gain : null,
    explicit: !!t.explicit_lyrics,
    rank: t.rank,
    genres: album?.genres?.data?.map((g) => g.name) || [],
    label: album?.label || null,
    contributors: (t.contributors || []).map((c) => ({ name: c.name, role: c.role })),
    links: { deezer: t.link },
  };
}

async function deezerSearch(artist, title, fallbackQuery) {
  const tries = [];
  if (artist && title) tries.push(`artist:"${artist}" track:"${title}"`);
  if (fallbackQuery) tries.push(fallbackQuery);
  if (title && !fallbackQuery) tries.push(title);
  for (const q of tries) {
    const r = await getJson(`https://api.deezer.com/search?limit=5&q=${encodeURIComponent(q)}`);
    if (r.data?.length) return deezerTrack(r.data[0].id);
  }
  return null;
}

async function itunesSearch(term, country = 'us') {
  const r = await getJson(
    `https://itunes.apple.com/search?entity=song&limit=1&country=${country}&term=${encodeURIComponent(term)}`
  );
  return r.results?.[0] ? fromItunes(r.results[0]) : null;
}

function fromItunes(x) {
  return {
    source: 'itunes',
    title: x.trackName,
    artist: x.artistName,
    album: x.collectionName,
    artwork: x.artworkUrl100?.replace(/\/\d+x\d+bb\./, '/600x600bb.'),
    preview: x.previewUrl || null,
    durationSec: x.trackTimeMillis ? Math.round(x.trackTimeMillis / 1000) : null,
    releaseDate: x.releaseDate?.slice(0, 10),
    genres: x.primaryGenreName ? [x.primaryGenreName] : [],
    explicit: x.trackExplicitness === 'explicit',
    contributors: [{ name: x.artistName, role: 'Main' }],
    links: { apple: x.trackViewUrl },
  };
}

/** 두 소스 결과를 합친다: primary 값을 우선하고 빈 칸만 secondary로 채움 */
function merge(primary, secondary) {
  if (!secondary) return primary;
  if (!primary) return secondary;
  const out = { ...secondary, ...Object.fromEntries(Object.entries(primary).filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && !v.length))) };
  out.links = { ...secondary.links, ...primary.links };
  return out;
}

export async function resolve(input) {
  let parsed = parseInput(input);

  if (parsed.platform === 'shortlink') {
    const res = await fetch(parsed.url, { redirect: 'follow', headers: { 'User-Agent': UA } });
    parsed = parseInput(res.url);
  }
  if (parsed.kind && parsed.kind !== 'track') {
    throw new ResolveError('지금은 곡(트랙) 단위 링크만 분석할 수 있어요. 플레이리스트·앨범 분석은 다음 단계 기능이에요.');
  }

  let track = null;
  let detected = null;

  switch (parsed.platform) {
    case 'deezer':
      track = await deezerTrack(parsed.id);
      break;

    case 'apple': {
      const r = await getJson(`https://itunes.apple.com/lookup?id=${parsed.id}&country=${parsed.country}`);
      const it = r.results?.find((x) => x.wrapperType === 'track') || r.results?.[0];
      if (!it) throw new ResolveError('Apple Music에서 곡을 찾지 못했어요.', 404);
      const base = fromItunes(it);
      track = merge(await deezerSearch(base.artist, base.title).catch(() => null), base);
      track.links = { ...track.links, apple: base.links.apple };
      break;
    }

    case 'spotify': {
      const info = parseSpotifyHtml(await getText(parsed.url));
      if (!info.title) throw new ResolveError('Spotify 페이지에서 곡 정보를 읽지 못했어요.', 502);
      detected = { title: info.title, artist: info.artist };
      track = await deezerSearch(info.artist, info.title, `${info.artist} ${info.title}`);
      track = merge(track, await itunesSearch(`${info.artist} ${info.title}`).catch(() => null));
      if (track && info.image && !track.artwork) track.artwork = info.image;
      if (track) track.links = { ...track.links, spotify: parsed.url };
      break;
    }

    case 'youtube': {
      const o = await getJson(
        `https://www.youtube.com/oembed?format=json&url=${encodeURIComponent(`https://www.youtube.com/watch?v=${parsed.id}`)}`
      );
      const c = cleanVideoTitle(o.title, o.author_name);
      detected = { title: o.title, artist: o.author_name, query: c.query };
      track = await deezerSearch(c.artist, c.title, c.query);
      track = merge(track, await itunesSearch(c.query).catch(() => null));
      if (track) track.links = { ...track.links, youtube: `https://www.youtube.com/watch?v=${parsed.id}` };
      break;
    }

    case 'search':
    default:
      track = await deezerSearch(null, null, parsed.query);
      track = merge(track, await itunesSearch(parsed.query).catch(() => null));
      break;
  }

  if (!track) throw new ResolveError('곡을 찾지 못했어요. "아티스트 곡명" 형태로 검색해 보세요.', 404);
  return { input: parsed, detected, track };
}
