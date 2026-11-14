import test from 'node:test';
import assert from 'node:assert/strict';
import { parseInput, cleanVideoTitle, parseSpotifyHtml } from '../lib/resolve.js';
import { isAllowedMedia } from '../server.js';

test('플랫폼별 링크 파싱', () => {
  assert.deepEqual(parseInput('https://open.spotify.com/intl-ko/track/0v1x6rN6JHRapa03JElljE?si=abc'),
    { platform: 'spotify', kind: 'track', id: '0v1x6rN6JHRapa03JElljE', url: 'https://open.spotify.com/track/0v1x6rN6JHRapa03JElljE' });
  assert.equal(parseInput('https://www.youtube.com/watch?v=gdZLi9oWNZg&t=10').id, 'gdZLi9oWNZg');
  assert.equal(parseInput('https://youtu.be/gdZLi9oWNZg?si=x').id, 'gdZLi9oWNZg');
  assert.equal(parseInput('https://music.youtube.com/watch?v=gdZLi9oWNZg').platform, 'youtube');
  assert.equal(parseInput('https://www.youtube.com/shorts/abcDEF12345').id, 'abcDEF12345');
  assert.deepEqual(parseInput('https://music.apple.com/kr/album/dynamite/1527734431?i=1527734437'),
    { platform: 'apple', kind: 'track', id: '1527734437', country: 'kr' });
  assert.equal(parseInput('https://music.apple.com/us/song/dynamite/1527734437').id, '1527734437');
  assert.deepEqual(parseInput('https://www.deezer.com/kr/track/1052512232'), { platform: 'deezer', kind: 'track', id: '1052512232' });
  assert.equal(parseInput('open.spotify.com/album/abc123').kind, 'album');
  assert.equal(parseInput('https://spotify.link/xyz').platform, 'shortlink');
  assert.deepEqual(parseInput('아이유 좋은 날'), { platform: 'search', query: '아이유 좋은 날' });
  assert.deepEqual(parseInput('NewJeans Hype Boy'), { platform: 'search', query: 'NewJeans Hype Boy' });
  assert.throws(() => parseInput('https://example.com/song'), /지원하지 않는/);
  assert.throws(() => parseInput('https://music.apple.com/kr/album/x/123'), /곡\(트랙\)/);
});

test('유튜브 제목 정리', () => {
  assert.equal(cleanVideoTitle("BTS (방탄소년단) 'Dynamite' Official MV", 'HYBE LABELS').query, 'BTS Dynamite');
  assert.deepEqual(cleanVideoTitle('Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams', 'Daft Punk'),
    { artist: 'Daft Punk', title: 'Get Lucky ft. Pharrell Williams', query: 'Daft Punk Get Lucky ft. Pharrell Williams' });
  assert.equal(cleanVideoTitle('[MV] IU(아이유) _ Good Day(좋은 날)', '1theK').query, 'IU _ Good Day');
  assert.equal(cleanVideoTitle('Ditto', 'NewJeans - Topic').query, 'NewJeans Ditto');
  assert.equal(cleanVideoTitle("Don't Stop Me Now (Remastered 2011) | Queen", 'Queen').query, "Don't Stop Me Now");
});

test('Spotify HTML 메타 파싱', () => {
  const html = `<html><head><title>Dynamite - song and lyrics by BTS | Spotify</title>
  <meta property="og:title" content="Dynamite"/><meta property="og:description" content="BTS · Song · 2020"/>
  <meta property="og:image" content="https://i.scdn.co/image/abc"/></head></html>`;
  assert.deepEqual(parseSpotifyHtml(html), { title: 'Dynamite', artist: 'BTS', image: 'https://i.scdn.co/image/abc' });
  const html2 = `<meta property="og:title" content="Love Dive"/><meta property="og:description" content="IVE · Love Dive · Song · 2022"/>`;
  assert.equal(parseSpotifyHtml(html2).artist, 'IVE');
});

test('미디어 프록시 허용 목록', () => {
  assert.ok(isAllowedMedia('https://cdnt-preview.dzcdn.net/api/1/1/a/b/c/0/x.mp3'));
  assert.ok(isAllowedMedia('https://is1-ssl.mzstatic.com/image/thumb/x/600x600bb.jpg'));
  assert.ok(isAllowedMedia('https://audio-ssl.itunes.apple.com/itunes-assets/x.m4a'));
  assert.ok(!isAllowedMedia('https://evil.com/?x=dzcdn.net'));
  assert.ok(!isAllowedMedia('https://dzcdn.net.evil.com/x'));
  assert.ok(!isAllowedMedia('http://cdnt-preview.dzcdn.net/x.mp3'));
  assert.ok(!isAllowedMedia('http://169.254.169.254/latest'));
});
