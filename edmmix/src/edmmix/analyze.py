"""Stage 3: measurement. Nothing here modifies audio."""
from __future__ import annotations

import warnings

import numpy as np
from scipy import signal

from .dsp.onsets import detect_onsets
from .dsp.util import db10, db20, f64, finite_or_none, to_mono

# Broad bands used for tone balance, mono compatibility and reference matching.
BROAD_BANDS: list[tuple[str, float, float]] = [
    ("sub", 20.0, 60.0),
    ("low", 60.0, 250.0),
    ("mid", 250.0, 2000.0),
    ("high_mid", 2000.0, 6000.0),
    ("high", 6000.0, 20000.0),
]

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


# ----------------------------------------------------------------------------- loudness

def _k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    import pyloudnorm as pyln

    meter = pyln.Meter(sr)
    y = x
    for filt in meter._filters.values():
        y = signal.lfilter(filt.b, filt.a, y, axis=0)
    return y


def integrated_lufs(x: np.ndarray, sr: int) -> float:
    """ITU-R BS.1770 gated integrated loudness. -inf for silence / too-short audio."""
    import pyloudnorm as pyln

    x = f64(x)
    if x.shape[0] < int(0.4 * sr) + 1 or not np.any(x):
        return float("-inf")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with np.errstate(divide="ignore", invalid="ignore"):
            value = float(pyln.Meter(sr).integrated_loudness(x))
    return value if np.isfinite(value) else float("-inf")


def short_term_lufs(x: np.ndarray, sr: int, window_s: float = 3.0, hop_s: float = 1.0) -> np.ndarray:
    """Short-term loudness (3 s window, ungated) every ``hop_s`` seconds."""
    x = f64(x)
    win, hop = int(window_s * sr), int(hop_s * sr)
    if x.shape[0] < win:
        return np.zeros(0)
    power = (_k_weight(x, sr) ** 2).sum(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, x.shape[0] - win + 1, hop)
    mean_sq = (csum[starts + win] - csum[starts]) / win
    return -0.691 + db10(mean_sq)


# ----------------------------------------------------------------------------- levels

def sample_peak_db(x: np.ndarray) -> float:
    return float(db20(np.max(np.abs(x)))) if x.size else -240.0


def true_peak_db(x: np.ndarray, oversample: int = 4) -> float:
    """Inter-sample peak estimate via 4x polyphase oversampling (dBTP)."""
    x = f64(x)
    if not np.any(x):
        return -240.0
    up = signal.resample_poly(x, oversample, 1, axis=0)
    return float(db20(max(np.max(np.abs(up)), np.max(np.abs(x)))))


def rms_db(x: np.ndarray) -> float:
    return float(db10(np.mean(f64(x) ** 2))) if x.size else -240.0


def active_rms_db(x: np.ndarray, sr: int, frame_s: float = 0.05, gate_db: float = 40.0) -> float:
    """RMS over frames within ``gate_db`` of the loudest frame (ignores silence)."""
    mono_power = (f64(x) ** 2).mean(axis=1) if x.ndim == 2 else f64(x) ** 2
    frame = max(1, int(frame_s * sr))
    n = mono_power.shape[0] // frame
    if n < 1:
        return float(db10(mono_power.mean())) if mono_power.size else -240.0
    frames = mono_power[:n * frame].reshape(n, frame).mean(axis=1)
    top = frames.max()
    if top <= 0.0:
        return -240.0
    active = frames[frames >= top * 10.0 ** (-gate_db / 10.0)]
    return float(db10(active.mean()))


def crest_factor_db(x: np.ndarray, sr: int) -> float:
    """Sample peak over active RMS, in dB."""
    return sample_peak_db(x) - active_rms_db(x, sr)


def stereo_correlation(x: np.ndarray) -> float:
    """Zero-lag L/R correlation coefficient in [-1, 1]; 1.0 for (near-)silent channels."""
    left, right = f64(x[:, 0]), f64(x[:, 1])
    denom = np.sqrt(np.dot(left, left) * np.dot(right, right))
    if denom <= 1e-20:
        return 1.0
    return float(np.dot(left, right) / denom)


def dc_offset(x: np.ndarray) -> list[float]:
    return [float(v) for v in f64(x).mean(axis=0)]


# ----------------------------------------------------------------------------- spectrum

def psd(x: np.ndarray, sr: int, nperseg: int = 16384) -> tuple[np.ndarray, np.ndarray]:
    """Welch PSD; stereo input -> average of the per-channel PSDs."""
    x = f64(x)
    nperseg = int(min(nperseg, x.shape[0]))
    freqs, p = signal.welch(x, fs=sr, nperseg=nperseg, axis=0)
    if p.ndim == 2:
        p = p.mean(axis=1)
    return freqs, p


def band_power(freqs: np.ndarray, p: np.ndarray, lo: float, hi: float) -> float:
    """Integrate a PSD between lo and hi (Hz); interpolates when the band is narrower than a bin."""
    hi = min(hi, freqs[-1])
    if hi <= lo:
        return 0.0
    df = freqs[1] - freqs[0]
    mask = (freqs >= lo) & (freqs < hi)
    if mask.sum() >= 2:
        return float(p[mask].sum() * df)
    return float(np.interp(np.sqrt(lo * hi), freqs, p) * (hi - lo))


def third_octave_centers(sr: int) -> np.ndarray:
    centers = 1000.0 * 2.0 ** (np.arange(-16, 14) / 3.0)  # 25 Hz .. 20 kHz
    return centers[centers * 2.0 ** (1.0 / 6.0) < 0.5 * sr]


def third_octave_from_psd(freqs: np.ndarray, p: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    centers = third_octave_centers(sr)
    edge = 2.0 ** (1.0 / 6.0)
    levels = np.array([db10(band_power(freqs, p, c / edge, c * edge)) for c in centers])
    return centers, levels


def third_octave_spectrum(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """1/3-octave band levels in dB (power per band, 0 dB = full-scale-squared)."""
    freqs, p = psd(x, sr)
    return third_octave_from_psd(freqs, p, sr)


def broad_band_levels_from_psd(freqs: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {name: float(db10(band_power(freqs, p, lo, hi))) for name, lo, hi in BROAD_BANDS}


def broad_band_balance(x: np.ndarray, sr: int) -> dict[str, float]:
    """Level of each broad band relative to the total 20 Hz-20 kHz power (dB)."""
    freqs, p = psd(x, sr)
    return relative_balance(broad_band_levels_from_psd(freqs, p))


def relative_balance(levels_db: dict[str, float]) -> dict[str, float]:
    total = db10(sum(10.0 ** (v / 10.0) for v in levels_db.values()))
    return {k: float(v - total) for k, v in levels_db.items()}


def spectral_features(x: np.ndarray, sr: int) -> dict[str, float]:
    """Features used by the heuristic classifier."""
    mono = to_mono(f64(x))
    freqs, p = psd(mono, sr, nperseg=4096)
    total = float(p.sum())
    if total <= 0.0:
        return {"centroid_hz": 0.0, "low_ratio": 0.0, "transient_density": 0.0, "flatness": 0.0}
    onsets = detect_onsets(mono, sr)
    audible = p[(freqs >= 20.0)]
    flatness = float(np.exp(np.mean(np.log(audible + 1e-30))) / (np.mean(audible) + 1e-30))
    return {
        "centroid_hz": float((freqs * p).sum() / total),
        "low_ratio": float(p[freqs < 120.0].sum() / total),
        "transient_density": float(len(onsets) / (mono.shape[0] / sr)),
        "flatness": flatness,
    }


# ----------------------------------------------------------------------------- musical analysis

def estimate_bpm(mono: np.ndarray, sr: int) -> dict:
    """Tempo via librosa beat tracking, refined by regressing beat times; snapped to
    an integer when within 0.35 BPM (EDM is almost always on an integer grid)."""
    import librosa

    y = np.asarray(mono, dtype=np.float32)
    if y.size < sr or float(np.max(np.abs(y))) < 1e-6:
        return {"bpm": None, "raw_bpm": None, "method": "none", "note": "signal too short or silent"}
    hop = 512
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop, start_bpm=128.0, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    if tempo <= 0.0:
        return {"bpm": None, "raw_bpm": None, "method": "none", "note": "no tempo found"}
    bpm, method = tempo, "librosa.beat_track"
    if len(beats) >= 8:
        times = np.asarray(beats, dtype=np.float64) * hop / sr
        slope = float(np.polyfit(np.arange(len(times)), times, 1)[0])
        if slope > 0 and abs(60.0 / slope - tempo) / tempo < 0.08:
            bpm, method = 60.0 / slope, "beat regression"
    while bpm < 70.0:
        bpm *= 2.0
    while bpm > 180.0:
        bpm /= 2.0
    raw = bpm
    if abs(bpm - round(bpm)) <= 0.35:
        bpm = float(round(bpm))
        method += ", snapped to integer"
    return {"bpm": round(float(bpm), 2), "raw_bpm": round(float(raw), 3), "method": method}


def estimate_key(mono: np.ndarray, sr: int) -> dict:
    """Krumhansl-Schmuckler key estimate from an averaged STFT chromagram."""
    import librosa

    y = np.asarray(mono, dtype=np.float32)
    if y.size < sr or float(np.max(np.abs(y))) < 1e-6:
        return {"key": None, "confidence": 0.0}
    n_fft = 1 << int(np.ceil(np.log2(0.18 * sr)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chroma = librosa.feature.chroma_stft(y=y, sr=sr, n_fft=n_fft, hop_length=n_fft // 2)
    profile = chroma.mean(axis=1).astype(np.float64)
    if not np.any(profile) or np.std(profile) < 1e-9:
        return {"key": None, "confidence": 0.0}
    scores = []
    for tonic in range(12):
        for mode, ref in (("major", _KS_MAJOR), ("minor", _KS_MINOR)):
            scores.append((float(np.corrcoef(profile, np.roll(ref, tonic))[0, 1]), tonic, mode))
    scores.sort(key=lambda s: (-s[0], s[1], s[2]))
    best, second = scores[0], scores[1]
    return {"key": f"{_NOTE_NAMES[best[1]]} {best[2]}",
            "confidence": round(best[0] - second[0], 3),
            "correlation": round(best[0], 3)}


def detect_sections(x: np.ndarray, sr: int, bpm: float | None) -> list[dict]:
    """Energy-based arrangement estimate on a one-bar grid.

    Bars whose full-band energy is within 4 dB of the loud reference (90th
    percentile) *and* whose low end (<150 Hz) is present are ``drop``. Quiet bars
    are ``intro`` (before the first drop), ``buildup`` (rising energy right before
    a drop, up to 8 bars) or ``breakdown``.
    """
    mono = to_mono(f64(x))
    n = mono.shape[0]
    bar_len = (4.0 * 60.0 / bpm if bpm else 2.0) * sr
    n_bars = int(n / bar_len + 0.05)
    if n_bars < 2 or not np.any(mono):
        return [{"label": "unknown", "start_s": 0.0, "end_s": round(n / sr, 3),
                 "start_bar": 0, "end_bar": n_bars}]
    edges = [min(n, int(round(i * bar_len))) for i in range(n_bars)] + [n]
    sos = signal.butter(4, 150.0, btype="lowpass", fs=sr, output="sos")
    low = signal.sosfilt(sos, mono)
    full_db = np.array([db10(np.mean(mono[edges[i]:edges[i + 1]] ** 2)) for i in range(n_bars)])
    low_db = np.array([db10(np.mean(low[edges[i]:edges[i + 1]] ** 2)) for i in range(n_bars)])
    full_ref, low_ref = np.percentile(full_db, 90), np.percentile(low_db, 90)
    is_drop = (full_db >= full_ref - 4.0) & (low_db >= low_ref - 6.0)

    labels = ["drop" if d else "low" for d in is_drop]
    i = 0
    while i < n_bars:
        if labels[i] != "low":
            i += 1
            continue
        j = i
        while j < n_bars and labels[j] == "low":
            j += 1
        build_start = j
        if j < n_bars:  # run leads into a drop: the rising tail (max 8 bars) is the build-up
            while build_start > max(i, j - 8) and (
                    build_start - 1 == i or full_db[build_start - 1] > full_db[build_start - 2] + 0.5):
                build_start -= 1
            if build_start == i and i == 0 and full_db[j - 1] <= full_db[i] + 1.0:
                build_start = j  # flat run from the very start is an intro, not a build-up
        for k in range(i, j):
            labels[k] = "buildup" if k >= build_start else ("intro" if i == 0 else "breakdown")
        i = j

    sections: list[dict] = []
    start = 0
    for k in range(1, n_bars + 1):
        if k == n_bars or labels[k] != labels[start]:
            sections.append({"label": labels[start], "start_s": round(edges[start] / sr, 3),
                             "end_s": round(edges[k] / sr, 3), "start_bar": start, "end_bar": k,
                             "mean_level_db": round(float(full_db[start:k].mean()), 2)})
            start = k
    return sections


# ----------------------------------------------------------------------------- aggregate

def analyze_audio(x: np.ndarray, sr: int, include_spectrum: bool = True) -> dict:
    """All per-signal measurements as a JSON-serialisable dict."""
    x = f64(x)
    st = short_term_lufs(x, sr)
    peak = sample_peak_db(x)
    out = {
        "integrated_lufs": finite_or_none(integrated_lufs(x, sr)),
        "short_term_lufs_max": finite_or_none(st.max()) if st.size else None,
        "short_term_lufs": [finite_or_none(v, 1) for v in st],
        "sample_peak_dbfs": finite_or_none(peak),
        "true_peak_dbtp": finite_or_none(true_peak_db(x)),
        "rms_dbfs": finite_or_none(rms_db(x)),
        "crest_factor_db": finite_or_none(crest_factor_db(x, sr)) if peak > -200 else None,
        "stereo_correlation": round(stereo_correlation(x), 4),
        "dc_offset": [round(v, 7) for v in dc_offset(x)],
    }
    if include_spectrum:
        freqs, p = psd(x, sr)
        centers, levels = third_octave_from_psd(freqs, p, sr)
        out["third_octave"] = {"centers_hz": [round(float(c), 1) for c in centers],
                               "levels_db": [finite_or_none(v, 1) for v in levels]}
        out["band_balance_db"] = {k: round(v, 2) for k, v in
                                  relative_balance(broad_band_levels_from_psd(freqs, p)).items()}
    return out


def analyze_global(mix: np.ndarray, tonal: np.ndarray | None, sr: int, bpm_override: float | None = None) -> dict:
    """Tempo, key and section estimates from the raw (unprocessed) stem sum."""
    mono = to_mono(f64(mix))
    if bpm_override:
        tempo = {"bpm": float(bpm_override), "raw_bpm": float(bpm_override), "method": "user override"}
    else:
        tempo = estimate_bpm(mono, sr)
    key_source = to_mono(f64(tonal)) if tonal is not None and np.any(tonal) else mono
    return {
        "tempo": tempo,
        "key": estimate_key(key_source, sr),
        "sections": detect_sections(mix, sr, tempo["bpm"]),
    }
