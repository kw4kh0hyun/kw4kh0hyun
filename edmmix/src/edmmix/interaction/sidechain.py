"""Kick-triggered ducking.

Instead of a compressor keyed by the kick audio, kick transients are detected once and a
gain envelope is *synthesised* at each onset (attack -> hold -> BPM-synced release). The
result is click-free, independent of kick level/tail, and fully described by a list of
onset positions plus four numbers - easy to inspect and edit in mix_params.json.
"""
from __future__ import annotations

import numpy as np

from ..dsp.onsets import detect_onsets
from ..dsp.util import from_db, rnd


def detect_kick_onsets(kick_mono: np.ndarray, sr: int, bpm: float) -> np.ndarray:
    """Kick transient positions (samples). Hits closer than ~a 16th note are merged."""
    sixteenth = 60.0 / bpm / 4.0
    return detect_onsets(kick_mono, sr, min_interval_s=max(0.05, 0.9 * sixteenth))


def release_ms(sc: dict, bpm: float) -> float:
    return float(sc["release_beats"]) * 60000.0 / float(bpm)


def ducking_shape(n: int, sr: int, onsets, sc: dict, bpm: float) -> np.ndarray:
    """0..1 envelope: 1 = full depth. Overlapping hits combine by maximum."""
    attack = max(1, int(round(float(sc["attack_ms"]) * 0.001 * sr)))
    hold = int(round(float(sc["hold_ms"]) * 0.001 * sr))
    release = max(1, int(round(release_ms(sc, bpm) * 0.001 * sr)))
    curve = float(sc.get("curve", 2.0))
    template = np.concatenate([
        np.arange(1, attack + 1) / attack,
        np.ones(hold),
        (1.0 - np.arange(1, release + 1) / release) ** curve,
    ])
    shape = np.zeros(n, dtype=np.float64)
    for onset in onsets:
        onset = int(onset)
        if 0 <= onset < n:
            end = min(n, onset + template.shape[0])
            np.maximum(shape[onset:end], template[:end - onset], out=shape[onset:end])
    return shape


def ducking_gain_db(n: int, sr: int, onsets, sc: dict, bpm: float) -> np.ndarray:
    return -float(sc["depth_db"]) * ducking_shape(n, sr, onsets, sc, bpm)


def apply(x: np.ndarray, sr: int, onsets, sc: dict, bpm: float) -> tuple[np.ndarray, dict]:
    if not sc.get("enabled") or float(sc.get("depth_db", 0.0)) <= 0.0 or len(onsets) == 0:
        return x, {"max_gain_reduction_db": 0.0}
    gain_db = ducking_gain_db(x.shape[0], sr, onsets, sc, bpm)
    return x * from_db(gain_db)[:, None], {"max_gain_reduction_db": round(float(-gain_db.min()), 2)}


def decide(role: str, preset: dict, bpm: float, n_onsets: int) -> dict:
    cfg = preset["sidechain"]
    depth = float(cfg.get("depth_db", {}).get(role, 0.0))
    base = {"enabled": False, "depth_db": 0.0, "attack_ms": rnd(cfg["attack_ms"], 2),
            "hold_ms": rnd(cfg["hold_ms"], 2), "release_beats": rnd(cfg["release_beats"], 4),
            "curve": rnd(cfg.get("curve", 2.0), 2)}
    if role == "kick":
        return {**base, "reason": "this is the side-chain source"}
    if n_onsets == 0:
        return {**base, "reason": "no kick transients found; nothing to duck against"}
    if depth <= 0.0:
        return {**base, "reason": f"preset '{preset['name']}' does not duck role '{role}'"}
    base.update(enabled=True, depth_db=rnd(depth, 2))
    ms = release_ms(base, bpm)
    return {**base, "reason": (f"preset '{preset['name']}' ducks '{role}' by {depth:g} dB under the kick; "
                               f"release {base['release_beats']:g} beat = {ms:.0f} ms at {bpm:g} BPM")}
