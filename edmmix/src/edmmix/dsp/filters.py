"""IIR filters (RBJ biquads, Butterworth high-pass) expressed as SOS sections."""
from __future__ import annotations

import numpy as np
from scipy import signal


def _sos(b0, b1, b2, a0, a1, a2) -> np.ndarray:
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _clamp_freq(freq_hz: float, sr: int) -> float:
    return float(min(max(freq_hz, 1.0), 0.49 * sr))


def peak_sos(freq_hz: float, gain_db: float, q: float, sr: int) -> np.ndarray:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * _clamp_freq(freq_hz, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    c = np.cos(w0)
    return _sos(1 + alpha * a, -2 * c, 1 - alpha * a, 1 + alpha / a, -2 * c, 1 - alpha / a)


def _shelf_sos(freq_hz: float, gain_db: float, q: float, sr: int, high: bool) -> np.ndarray:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * _clamp_freq(freq_hz, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    c = np.cos(w0)
    s = 2.0 * np.sqrt(a) * alpha
    if high:
        return _sos(
            a * ((a + 1) + (a - 1) * c + s),
            -2 * a * ((a - 1) + (a + 1) * c),
            a * ((a + 1) + (a - 1) * c - s),
            (a + 1) - (a - 1) * c + s,
            2 * ((a - 1) - (a + 1) * c),
            (a + 1) - (a - 1) * c - s,
        )
    return _sos(
        a * ((a + 1) - (a - 1) * c + s),
        2 * a * ((a - 1) - (a + 1) * c),
        a * ((a + 1) - (a - 1) * c - s),
        (a + 1) + (a - 1) * c + s,
        -2 * ((a - 1) + (a + 1) * c),
        (a + 1) + (a - 1) * c - s,
    )


def low_shelf_sos(freq_hz, gain_db, q, sr):
    return _shelf_sos(freq_hz, gain_db, q, sr, high=False)


def high_shelf_sos(freq_hz, gain_db, q, sr):
    return _shelf_sos(freq_hz, gain_db, q, sr, high=True)


def bandpass_sos(freq_hz: float, q: float, sr: int) -> np.ndarray:
    """RBJ band-pass with 0 dB peak gain and zero phase at the centre frequency."""
    w0 = 2.0 * np.pi * _clamp_freq(freq_hz, sr) / sr
    alpha = np.sin(w0) / (2.0 * q)
    c = np.cos(w0)
    return _sos(alpha, 0.0, -alpha, 1 + alpha, -2 * c, 1 - alpha)


def highpass_sos(cutoff_hz: float, order: int, sr: int) -> np.ndarray:
    return signal.butter(int(order), _clamp_freq(cutoff_hz, sr), btype="highpass", fs=sr, output="sos")


def lowpass_sos(cutoff_hz: float, order: int, sr: int) -> np.ndarray:
    return signal.butter(int(order), _clamp_freq(cutoff_hz, sr), btype="lowpass", fs=sr, output="sos")


def eq_band_sos(band: dict, sr: int) -> np.ndarray:
    """Build one SOS section from a JSON EQ band: {type, freq_hz, gain_db, q}."""
    kind = band.get("type", "peak")
    freq, gain, q = float(band["freq_hz"]), float(band["gain_db"]), float(band.get("q", 0.707))
    if kind == "peak":
        return peak_sos(freq, gain, q, sr)
    if kind == "low_shelf":
        return low_shelf_sos(freq, gain, q, sr)
    if kind == "high_shelf":
        return high_shelf_sos(freq, gain, q, sr)
    raise ValueError(f"unknown EQ band type: {kind!r}")


def eq_sos(bands: list[dict], sr: int) -> np.ndarray | None:
    """Cascade of EQ bands; bands with 0 dB gain are skipped. None if nothing to do."""
    sections = [eq_band_sos(b, sr) for b in bands if float(b.get("gain_db", 0.0)) != 0.0]
    return np.vstack(sections) if sections else None


def apply_sos(x: np.ndarray, sos: np.ndarray | None) -> np.ndarray:
    if sos is None:
        return x
    return signal.sosfilt(sos, x, axis=0)


def sos_power_response(sos: np.ndarray | None, freqs_hz: np.ndarray, sr: int) -> np.ndarray:
    """|H(f)|^2 at the given frequencies."""
    if sos is None:
        return np.ones_like(freqs_hz, dtype=np.float64)
    _, h = signal.sosfreqz(sos, worN=freqs_hz, fs=sr)
    return np.abs(h) ** 2
