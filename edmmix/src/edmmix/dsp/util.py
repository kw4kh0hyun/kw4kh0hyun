"""Small numeric helpers shared by every module."""
from __future__ import annotations

import numpy as np

AMP_FLOOR = 1e-12
POW_FLOOR = 1e-24


def db20(amplitude):
    """Amplitude -> dB, floored at -240 dB."""
    return 20.0 * np.log10(np.maximum(amplitude, AMP_FLOOR))


def db10(power):
    """Power -> dB, floored at -240 dB."""
    return 10.0 * np.log10(np.maximum(power, POW_FLOOR))


def from_db(gain_db):
    return 10.0 ** (np.asarray(gain_db, dtype=np.float64) / 20.0)


def to_mono(x: np.ndarray) -> np.ndarray:
    """(n, 2) -> (n,) average of channels."""
    return x.mean(axis=1) if x.ndim == 2 else x


def f64(x: np.ndarray) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)


def rnd(value, digits: int = 3) -> float:
    """Round to a plain Python float so parameters serialise cleanly to JSON."""
    return float(round(float(value), digits))


def finite_or_none(value, digits: int = 2):
    """JSON-safe number: None for -inf/nan."""
    value = float(value)
    if not np.isfinite(value):
        return None
    return float(round(value, digits))
