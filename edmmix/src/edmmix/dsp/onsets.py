"""Transient (onset) detection on a mono signal, sample-accurate enough for side-chaining."""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def _pick(env, rel_coef, abs_thresh, rise_ratio, min_gap):
    out = np.empty(env.shape[0], dtype=np.int64)
    count = 0
    follower = 0.0
    last = -min_gap
    for i in range(env.shape[0]):
        v = env[i]
        if v > abs_thresh and v > rise_ratio * follower and i - last >= min_gap:
            out[count] = i
            count += 1
            last = i
        follower = v if v > follower else rel_coef * follower
    return out[:count]


def detect_onsets(x: np.ndarray, sr: int, min_interval_s: float = 0.08,
                  threshold_db: float = -30.0, rise_db: float = 6.0) -> np.ndarray:
    """Return onset positions in samples.

    A 1 ms peak envelope is compared against a decaying follower (30 ms release);
    an onset fires when the envelope jumps ``rise_db`` above the follower and is
    louder than ``threshold_db`` relative to the signal peak. Each onset is then
    refined to the first sample reaching 20 % of the local peak.
    """
    x = np.abs(np.asarray(x, dtype=np.float64))
    peak = float(x.max()) if x.size else 0.0
    if peak <= 1e-9:
        return np.zeros(0, dtype=np.int64)
    hop = max(1, int(round(sr * 0.001)))
    n_frames = x.shape[0] // hop
    if n_frames < 2:
        return np.zeros(0, dtype=np.int64)
    env = x[:n_frames * hop].reshape(n_frames, hop).max(axis=1)
    frame_rate = sr / hop
    rel_coef = float(np.exp(-1.0 / (0.030 * frame_rate)))
    frames = _pick(env, rel_coef, peak * 10.0 ** (threshold_db / 20.0),
                   10.0 ** (rise_db / 20.0), max(1, int(round(min_interval_s * frame_rate))))
    onsets = np.empty(frames.shape[0], dtype=np.int64)
    look = int(round(0.010 * sr))
    for k, f in enumerate(frames):
        start = max(0, (int(f) - 1) * hop)
        seg = x[start:start + hop + look]
        above = np.nonzero(seg >= 0.2 * seg.max())[0]
        onsets[k] = start + (int(above[0]) if above.size else hop)
    return onsets
