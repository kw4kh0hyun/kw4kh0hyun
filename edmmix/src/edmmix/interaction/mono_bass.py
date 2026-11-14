"""Mono-ise the low end with a linear-phase crossover.

side = (L - R) / 2 is split by a linear-phase FIR low-pass; the low part of the side
signal is discarded, everything else is untouched: L' = L - low(side), R' = R + low(side).
Because the FIR delay is compensated and the high band is formed by subtraction, the mid
signal and everything above the crossover pass bit-transparently in phase.
"""
from __future__ import annotations

import numpy as np

from ..dsp.linear_phase import design_lowpass, lowpass_zero_delay


def apply(x: np.ndarray, sr: int, mb: dict) -> np.ndarray:
    if not mb.get("enabled"):
        return x
    if np.array_equal(x[:, 0], x[:, 1]):
        return x                                   # already mono: side is exactly zero
    taps = design_lowpass(float(mb["freq_hz"]), float(mb.get("transition_hz", 60.0)),
                          float(mb.get("attenuation_db", 80.0)), int(sr))
    side_low = lowpass_zero_delay(0.5 * (x[:, 0] - x[:, 1]), taps)
    return np.stack([x[:, 0] - side_low, x[:, 1] + side_low], axis=1)


def decide() -> dict:
    return {"enabled": True, "freq_hz": 120.0, "transition_hz": 60.0, "attenuation_db": 80.0,
            "reason": ("side signal removed below 120 Hz with a linear-phase FIR (pass-band to 120 Hz, "
                       "80 dB down by 180 Hz) for mono-safe, club-safe low end")}
