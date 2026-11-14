"""Recursive envelope followers (numba-compiled, no fastmath -> deterministic)."""
from __future__ import annotations

import numpy as np
from numba import njit


def time_coef(time_ms: float, sr: float) -> float:
    """One-pole smoothing coefficient for a time constant in milliseconds."""
    if time_ms <= 0.0:
        return 0.0
    return float(np.exp(-1.0 / (time_ms * 0.001 * sr)))


@njit(cache=True)
def _smooth_ar(x, a_att, a_rel):
    y = np.empty_like(x)
    s = 0.0
    for i in range(x.shape[0]):
        v = x[i]
        c = a_att if v > s else a_rel
        s = c * s + (1.0 - c) * v
        y[i] = s
    return y


def smooth_attack_release(x: np.ndarray, attack_ms: float, release_ms: float, sr: float) -> np.ndarray:
    """Asymmetric one-pole smoother: rising input uses attack, falling uses release."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    return _smooth_ar(x, time_coef(attack_ms, sr), time_coef(release_ms, sr))
