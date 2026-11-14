"""WAV writing with explicit, deterministic 24-bit quantisation (no dither)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

_FULL_SCALE = float(2 ** 23)


def quantize24(x: np.ndarray) -> np.ndarray:
    """float -> 24-bit integer sample values (int32 array in [-2^23, 2^23-1])."""
    q = np.rint(np.asarray(x, dtype=np.float64) * _FULL_SCALE)
    return np.clip(q, -_FULL_SCALE, _FULL_SCALE - 1).astype(np.int32)


def dequantize24(q: np.ndarray) -> np.ndarray:
    return q.astype(np.float64) / _FULL_SCALE


def write_wav24(path: str | Path, x: np.ndarray, sr: int) -> None:
    # libsndfile takes the top 24 bits of int32 data for PCM_24.
    sf.write(str(path), quantize24(x) << 8, sr, subtype="PCM_24")


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return data, sr
