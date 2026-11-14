"""Stage 7: mix bus. Gain only - no limiter, no clipper, no dynamics of any kind."""
from __future__ import annotations

import numpy as np

from .dsp.util import db20, from_db


def peak_normalising_gain_db(mix: np.ndarray, target_peak_dbfs: float) -> float:
    """Gain that puts the sample peak of ``mix`` exactly on the target. 0 dB for silence."""
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak <= 1e-12:
        return 0.0
    return float(target_peak_dbfs - db20(peak))


def resolve_gain_db(mix: np.ndarray, mixbus_params: dict) -> float:
    if mixbus_params.get("gain_mode", "auto") == "fixed":
        return float(mixbus_params["gain_db"])
    return peak_normalising_gain_db(mix, float(mixbus_params["target_peak_dbfs"]))


def apply_gain(x: np.ndarray, gain_db: float) -> np.ndarray:
    return x * float(from_db(gain_db))
