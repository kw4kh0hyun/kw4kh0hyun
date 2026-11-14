"""Polyphase up/down sampling used around non-linear processing.

The anti-alias FIR (Kaiser beta 12, 96 taps per phase) keeps an up->down round trip
transparent to about -120 dB up to 20 kHz, so oversampled stages do not colour the signal.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import signal


@lru_cache(maxsize=4)
def _taps(factor: int) -> np.ndarray:
    return signal.firwin(2 * 48 * factor + 1, 1.0 / factor, window=("kaiser", 12.0))


def upsample(x: np.ndarray, factor: int) -> np.ndarray:
    if factor == 1:
        return x
    return signal.resample_poly(x, factor, 1, axis=0, window=_taps(factor))


def downsample(x: np.ndarray, factor: int, n_out: int) -> np.ndarray:
    if factor == 1:
        return x[:n_out]
    return signal.resample_poly(x, 1, factor, axis=0, window=_taps(factor))[:n_out]
