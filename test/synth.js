// 테스트용 합성 음원: 지정 BPM의 킥/하이햇 + 지정 키의 코드 진행
export function synth({ bpm, chords, seconds = 30, sr = 22050, quietIntro = 0 }) {
  const x = new Float32Array(seconds * sr);
  const beat = 60 / bpm;
  const midiHz = (m) => 440 * 2 ** ((m - 69) / 12);
  for (let i = 0; i < x.length; i++) {
    const t = i / sr;
    const bar = Math.floor(t / (beat * 4));
    const chord = chords[bar % chords.length];
    let s = 0;
    for (const m of chord) s += 0.08 * Math.sin(2 * Math.PI * midiHz(m) * t) + 0.03 * Math.sin(4 * Math.PI * midiHz(m) * t);
    s += 0.12 * Math.sin(2 * Math.PI * midiHz(chord[0] - 12) * t);
    const tb = t % beat;
    s += 0.6 * Math.exp(-tb * 30) * Math.sin(2 * Math.PI * (60 + 80 * Math.exp(-tb * 40)) * tb);
    const th = (t + beat / 2) % beat;
    s += 0.15 * Math.exp(-th * 80) * (Math.random() * 2 - 1);
    const gain = t < quietIntro ? 0.25 : 1;
    x[i] = s * gain;
  }
  return x;
}
// 코드(미디 노트)
export const A_MINOR = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]; // Am F C G
export const D_MAJOR = [[50, 54, 57], [55, 59, 62], [57, 61, 64], [50, 54, 57]]; // D G A D
