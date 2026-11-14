"""Polyphase up/down sampling used around non-linear processing."""
from __future__ import annotations

import numpy as np
from scipy import signal


def upsample(x: np.ndarray, factor: int) -> np.ndarray:
    if factor == 1:
        return x
    return signal.resample_poly(x, factor, 1, axis=0)


def downsample(x: np.ndarray, factor: int, n_out: int) -> np.ndarray:
    if factor == 1:
        return x[:n_out]
    return signal.resample_poly(x, 1, factor, axis=0)[:n_out]
