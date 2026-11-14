import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeSamples, camelot, camelotNeighbors, buildInsights } from '../public/analysis.js';
import { synth, A_MINOR, D_MAJOR } from './synth.js';

const near = (a, b, tol) => Math.abs(a - b) <= tol || Math.abs(a - 2 * b) <= tol || Math.abs(2 * a - b) <= tol;

test('124 BPM A단조 합성곡', () => {
  const r = analyzeSamples(synth({ bpm: 124, chords: A_MINOR }));
  console.log(JSON.stringify({ bpm: r.bpm, key: r.key, features: r.features, mood: r.mood.ko, b: r.boundaries }));
  assert.ok(Math.abs(r.bpm - 124) < 2, `bpm ${r.bpm}`);
  assert.ok(['Am', 'C'].includes(r.key.name), `key ${r.key.name}`);
});

test('92 BPM D장조 합성곡 + 조용한 인트로', () => {
  const r = analyzeSamples(synth({ bpm: 92, chords: D_MAJOR, quietIntro: 8 }));
  console.log(JSON.stringify({ bpm: r.bpm, key: r.key, features: r.features, mood: r.mood.ko, b: r.boundaries, peak: r.peakSec }));
  assert.ok(near(r.bpm, 92, 2), `bpm ${r.bpm}`);
  assert.equal(r.key.name, 'D');
  assert.ok(r.boundaries.some((b) => Math.abs(b - 8) <= 1.5), `boundaries ${r.boundaries}`);
  assert.ok(buildInsights(r).length >= 4);
});

test('캠롯 표기', () => {
  assert.equal(camelot(0, 'major'), '8B');
  assert.equal(camelot(9, 'minor'), '8A');
  assert.equal(camelot(5, 'major'), '7B');
  assert.equal(camelot(0, 'minor'), '5A');
  assert.equal(camelot(4, 'major'), '12B');
  assert.deepEqual(camelotNeighbors('12B').map((n) => n.code), ['12B', '1B', '11B', '12A']);
});
