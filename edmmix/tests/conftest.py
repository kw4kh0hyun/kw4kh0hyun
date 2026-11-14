from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from make_stems import write_stem_set  # noqa: E402

SR = 44100


@pytest.fixture(scope="session")
def stems_dir(tmp_path_factory) -> Path:
    return write_stem_set(tmp_path_factory.mktemp("stems"), SR)


@pytest.fixture(scope="session")
def sr() -> int:
    return SR


def sine(freq: float, seconds: float, sr: int = SR, amp: float = 1.0, phase: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t + phase)


def stereo(left: np.ndarray, right: np.ndarray | None = None) -> np.ndarray:
    return np.stack([left, left if right is None else right], axis=1)


def tone_level_db(x: np.ndarray, freq: float, sr: int = SR) -> float:
    """Amplitude (dB) of the component at ``freq`` via projection onto a windowed complex tone."""
    n = x.shape[0]
    w = np.hanning(n)
    t = np.arange(n) / sr
    amp = 2 * abs(np.sum(x * w * np.exp(-2j * np.pi * freq * t))) / np.sum(w)
    return float(20 * np.log10(max(amp, 1e-15)))
