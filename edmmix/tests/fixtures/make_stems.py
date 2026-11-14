"""Generate a small synthetic stem set (8 bars @ 128 BPM) for tests and demos.

Usage: python tests/fixtures/make_stems.py <out_dir> [--sr 44100]

Arrangement: bars 0-1 intro (pad + hats), bars 2-3 build-up (+ clap, riser),
bars 4-7 drop (everything). All signals are deterministic (seeded noise).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

BPM = 128.0
BARS = 8


def _env_decay(n: int, sr: int, tau_s: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (tau_s * sr))


def _place(track: np.ndarray, hit: np.ndarray, start: int) -> None:
    end = min(track.shape[0], start + hit.shape[0])
    if start < track.shape[0]:
        track[start:end] += hit[:end - start]


def _saw(freq: float, n: int, sr: int, phase: float = 0.0) -> np.ndarray:
    """Band-limited sawtooth (additive, harmonics below 0.45 * sr)."""
    t = np.arange(n) / sr
    out = np.zeros(n)
    k = 1
    while k * freq < 0.45 * sr and k <= 60:
        out += np.sin(2 * np.pi * k * freq * t + k * phase) / k
        k += 1
    return out * (2 / np.pi)


def kick_hit(sr: int) -> np.ndarray:
    n = int(0.30 * sr)
    t = np.arange(n) / sr
    freq = 45.0 + 110.0 * np.exp(-t / 0.035)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = np.sin(phase) * np.exp(-t / 0.09)
    click = np.exp(-t / 0.002) * 0.4
    return body + click


def beat_positions(sr: int, bars: range, steps_per_bar: int, offset_steps: float = 0.0) -> list[int]:
    step = 4 * 60.0 / BPM / steps_per_bar
    return [int(round((bar * steps_per_bar + i + offset_steps) * step * sr))
            for bar in bars for i in range(steps_per_bar)]


def make_stems(sr: int = 44100, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    bar = 4 * 60.0 / BPM
    n = int(round(BARS * bar * sr))
    t = np.arange(n) / sr
    drop_start = int(round(4 * bar * sr))
    build_start = int(round(2 * bar * sr))
    drop_gate = (np.arange(n) >= drop_start).astype(float)
    stems: dict[str, np.ndarray] = {}

    # kick: four-on-the-floor in the drop
    kick = np.zeros(n)
    for pos in beat_positions(sr, range(4, 8), 4):
        _place(kick, kick_hit(sr), pos)
    stems["kick"] = np.stack([kick, kick], axis=1) * 0.8

    # sub: sustained 55 Hz sine in the drop (mono)
    sub = np.sin(2 * np.pi * 55.0 * t) * drop_gate * 0.5
    stems["sub"] = np.stack([sub, sub], axis=1)

    # bass: off-beat saw notes, slightly different phase per channel (low side content)
    note = int(0.2 * sr)
    bass_l, bass_r = np.zeros(n), np.zeros(n)
    shape = np.minimum(1.0, np.arange(note) / (0.005 * sr)) * _env_decay(note, sr, 0.12)
    for pos in beat_positions(sr, range(4, 8), 4, offset_steps=0.5):
        _place(bass_l, _saw(110.0, note, sr) * shape, pos)
        _place(bass_r, _saw(110.0, note, sr, phase=0.6) * shape, pos)
    stems["bass"] = np.stack([bass_l, bass_r], axis=1) * 0.4

    # hats: high-passed noise bursts on off-beat 8ths, whole track
    hp = signal.butter(4, 7000.0, btype="highpass", fs=sr, output="sos")
    hats = np.zeros(n)
    burst_n = int(0.06 * sr)
    for pos in beat_positions(sr, range(0, 8), 4, offset_steps=0.5):
        burst = signal.sosfilt(hp, rng.standard_normal(burst_n)) * _env_decay(burst_n, sr, 0.015)
        _place(hats, burst, pos)
    stems["hats"] = np.stack([hats, hats], axis=1) * 0.25

    # clap: band-passed noise on beats 2 and 4 from the build-up on
    bp = signal.butter(2, [900.0, 3500.0], btype="bandpass", fs=sr, output="sos")
    clap_l, clap_r = np.zeros(n), np.zeros(n)
    clap_n = int(0.15 * sr)
    beat = 60.0 / BPM
    for bar_idx in range(2, 8):
        for b in (1, 3):
            pos = int(round((bar_idx * 4 + b) * beat * sr))
            env = _env_decay(clap_n, sr, 0.04)
            _place(clap_l, signal.sosfilt(bp, rng.standard_normal(clap_n)) * env, pos)
            _place(clap_r, signal.sosfilt(bp, rng.standard_normal(clap_n)) * env, pos)
    stems["clap"] = np.stack([clap_l, clap_r], axis=1) * 0.3

    # lead: 8th-note saw melody in the drop, right channel delayed 7 ms
    melody = [440.0, 523.25, 659.25, 523.25, 587.33, 523.25, 440.0, 392.0]
    lead = np.zeros(n)
    note = int(0.21 * sr)
    shape = np.minimum(1.0, np.arange(note) / (0.004 * sr)) * _env_decay(note, sr, 0.15)
    for i, pos in enumerate(beat_positions(sr, range(4, 8), 8)):
        _place(lead, _saw(melody[i % len(melody)], note, sr) * shape, pos)
    delay = int(0.007 * sr)
    lead_r = np.concatenate([np.zeros(delay), lead[:-delay]])
    stems["lead"] = np.stack([lead, lead_r], axis=1) * 0.3

    # pad: A-minor triad, detuned between channels, whole track
    pad_l = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 261.63, 329.63))
    pad_r = sum(np.sin(2 * np.pi * f * 1.003 * t + 0.5) for f in (220.0, 261.63, 329.63))
    stems["pad"] = np.stack([pad_l, pad_r], axis=1) * 0.08

    # vocal: vibrato saw through two formant band-passes, phrases in the drop
    vib = 220.0 * (1 + 0.01 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(vib) / sr
    src = sum(np.sin(k * phase) / k for k in range(1, 30))
    formants = sum(signal.sosfilt(signal.butter(2, [f * 0.85, f * 1.15], btype="bandpass", fs=sr,
                                                output="sos"), src) for f in (800.0, 1200.0, 2600.0))
    phrase = (np.sin(2 * np.pi * t / (2 * bar)) > -0.2).astype(float)
    phrase = signal.sosfilt(signal.butter(1, 20.0, fs=sr, output="sos"), phrase)
    vocal = formants * phrase * drop_gate
    stems["vocal"] = np.stack([vocal, vocal], axis=1) * 0.25

    # fx: noise riser during the build-up
    riser = np.zeros(n)
    seg = drop_start - build_start
    ramp = (np.arange(seg) / seg) ** 2
    noise = signal.sosfilt(signal.butter(2, 2000.0, btype="highpass", fs=sr, output="sos"),
                           rng.standard_normal(seg))
    riser[build_start:drop_start] = noise * ramp
    stems["fx_riser"] = np.stack([riser, riser * 0.9], axis=1) * 0.12

    return stems


def write_stem_set(out_dir: str | Path, sr: int = 44100, seed: int = 0) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, audio in make_stems(sr, seed).items():
        sf.write(str(out_dir / f"{name}.wav"), audio, sr, subtype="PCM_24")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir")
    parser.add_argument("--sr", type=int, default=44100)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    print(f"wrote stems to {write_stem_set(args.out_dir, args.sr, args.seed)}")
