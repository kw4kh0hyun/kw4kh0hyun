"""Kick vs. sub/bass phase check.

Looks at the low band (<150 Hz) in the windows right after each kick hit and asks: would
the kick+bass sum be louder with the bass polarity flipped and/or shifted by a few samples?
The answer is a *suggestion* (``apply: false``); set ``apply: true`` in mix_params.json and
re-render to use it.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from ..dsp.util import db10

LOW_BAND_HZ = 150.0
WINDOW_S = 0.15
MAX_DELAY_MS = 5.0
MIN_IMPROVEMENT_DB = 1.0
SIMPLICITY_MARGIN_DB = 0.5


def _none(reason: str) -> dict:
    return {"apply": False, "invert_polarity": False, "delay_samples": 0, "reason": reason}


def analyse(kick_mono: np.ndarray, other_mono: np.ndarray, sr: int, onsets) -> dict:
    if len(onsets) == 0:
        return _none("no kick transients; phase not analysed")
    sos = signal.butter(4, LOW_BAND_HZ, btype="lowpass", fs=sr, output="sos")
    kick = signal.sosfiltfilt(sos, kick_mono)
    other = signal.sosfiltfilt(sos, other_mono)
    n = kick.shape[0]
    mask = np.zeros(n, dtype=bool)
    window = int(WINDOW_S * sr)
    onsets = np.asarray(onsets, dtype=np.int64)
    for i, onset in enumerate(onsets):
        end = min(n, int(onset) + window, int(onsets[i + 1]) if i + 1 < len(onsets) else n)
        mask[int(onset):end] = True
    kick_w = kick * mask
    e_kick = float(np.dot(kick_w, kick_w))
    e_other = float(np.dot(other * mask, other * mask))
    if e_kick <= 1e-12 or e_other <= 1e-12 or e_other < e_kick * 1e-4:
        return _none("no significant low-frequency overlap with the kick; nothing to align")

    max_delay = int(round(MAX_DELAY_MS * 0.001 * sr))
    corr = signal.correlate(kick_w, other, mode="full", method="fft")
    lags = signal.correlation_lags(n, n, mode="full")
    keep = np.abs(lags) <= max_delay
    corr, lags = corr[keep], lags[keep]             # corr[d] = sum kick[m] * other[m - d]

    def energy(polarity: int, c: float) -> float:
        return max(e_kick + e_other + 2.0 * polarity * c, 1e-20)

    now = energy(+1, float(corr[lags == 0][0]))
    i_pos, i_neg = int(np.argmax(corr)), int(np.argmin(corr))
    options = [   # (invert, delay, improvement dB), simplest first
        (True, 0, db10(energy(-1, float(corr[lags == 0][0])) / now)),
        (False, int(lags[i_pos]), db10(energy(+1, float(corr[i_pos])) / now)),
        (True, int(lags[i_neg]), db10(energy(-1, float(corr[i_neg])) / now)),
    ]
    best = max(o[2] for o in options)
    stats = f"kick+stem low-band sum in the {WINDOW_S * 1000:.0f} ms after each kick"
    if best < MIN_IMPROVEMENT_DB:
        return _none(f"aligned: no polarity/delay change improves the {stats} by {MIN_IMPROVEMENT_DB:g} dB "
                     f"(best {best:+.2f} dB)")
    invert, delay, gain = next(o for o in options if o[2] >= best - SIMPLICITY_MARGIN_DB)
    what = []
    if invert:
        what.append("polarity inversion")
    if delay:
        what.append(f"{'delaying' if delay > 0 else 'advancing'} by {abs(delay)} samples "
                    f"({abs(delay) / sr * 1000:.2f} ms)")
    return {"apply": False, "invert_polarity": bool(invert), "delay_samples": int(delay),
            "reason": (f"suggestion: {' + '.join(what)} raises the {stats} by {gain:.1f} dB. "
                       "Not applied automatically - set \"apply\": true and re-render to use it")}


def apply(x: np.ndarray, phase: dict) -> np.ndarray:
    if not phase.get("apply"):
        return x
    y = -x if phase.get("invert_polarity") else x
    delay = int(phase.get("delay_samples", 0))
    if delay == 0:
        return y
    out = np.zeros_like(y)
    if delay > 0:
        out[delay:] = y[:-delay]
    else:
        out[:delay] = y[-delay:]
    return out
