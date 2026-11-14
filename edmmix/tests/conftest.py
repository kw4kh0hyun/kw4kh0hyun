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


@pytest.fixture(scope="session")
def mix_out(stems_dir, tmp_path_factory) -> Path:
    """One full `edmmix mix` run shared by the end-to-end tests."""
    from edmmix.cli import main

    out = tmp_path_factory.mktemp("mix_out")
    assert main(["mix", str(stems_dir), "-o", str(out)]) == 0
    return out


def read_pcm24(path) -> np.ndarray:
    """Exact 24-bit sample values as int64."""
    import soundfile as sf

    data, _ = sf.read(str(path), dtype="int32", always_2d=True)
    return (data >> 8).astype(np.int64)


def dir_bytes(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}
