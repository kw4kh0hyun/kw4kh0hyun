"""Linear-phase FIR low-pass with latency compensation (zero net delay)."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import signal


@lru_cache(maxsize=8)
def design_lowpass(passband_hz: float, transition_hz: float, attenuation_db: float, sr: int) -> np.ndarray:
    """Kaiser-windowed FIR: flat up to passband_hz, stop-band from passband_hz + transition_hz."""
    numtaps, beta = signal.kaiserord(attenuation_db, transition_hz / (0.5 * sr))
    numtaps |= 1  # odd -> integer group delay
    cutoff = passband_hz + 0.5 * transition_hz
    return signal.firwin(numtaps, cutoff, window=("kaiser", beta), fs=sr)


def lowpass_zero_delay(x: np.ndarray, taps: np.ndarray) -> np.ndarray:
    """Filter along axis 0 and remove the FIR group delay so output is time-aligned."""
    delay = (len(taps) - 1) // 2
    n = x.shape[0]
    if x.ndim == 1:
        return signal.fftconvolve(x, taps, mode="full")[delay:delay + n]
    return signal.fftconvolve(x, taps[:, None], mode="full", axes=0)[delay:delay + n]
