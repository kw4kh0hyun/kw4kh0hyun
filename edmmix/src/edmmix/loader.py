"""Stage 1: load a folder of stems, validate, unify to stereo."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf


class StemLoadError(Exception):
    """Raised when the stems folder cannot be used as a consistent stem set."""


@dataclass
class Stem:
    name: str            # file name without extension; key used everywhere
    path: Path
    audio: np.ndarray    # (n_samples, 2) float32, exactly as stored in the file
    sample_rate: int
    source_channels: int
    subtype: str


@dataclass
class StemSet:
    directory: Path
    sample_rate: int
    n_samples: int
    stems: list[Stem] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.stems]

    def get(self, name: str) -> Stem:
        for s in self.stems:
            if s.name == name:
                return s
        raise KeyError(name)

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate


def load_stems(directory: str | Path) -> StemSet:
    directory = Path(directory)
    if not directory.is_dir():
        raise StemLoadError(f"stems directory not found: {directory}")
    paths = sorted((p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".wav"),
                   key=lambda p: p.name.lower())
    if not paths:
        raise StemLoadError(f"no .wav files found in {directory}")

    stems: list[Stem] = []
    for path in paths:
        try:
            info = sf.info(str(path))
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:  # corrupt / unsupported file
            raise StemLoadError(f"cannot read {path.name}: {exc}") from exc
        channels = data.shape[1]
        if channels == 1:
            data = np.repeat(data, 2, axis=1)
        elif channels != 2:
            raise StemLoadError(
                f"{path.name}: {channels} channels; only mono or stereo stems are supported")
        if data.shape[0] == 0:
            raise StemLoadError(f"{path.name}: file contains no audio")
        if not np.all(np.isfinite(data)):
            raise StemLoadError(f"{path.name}: contains NaN/Inf samples")
        stems.append(Stem(path.stem, path, np.ascontiguousarray(data), int(sr), channels, info.subtype))

    names = [s.name for s in stems]
    if len(set(names)) != len(names):
        raise StemLoadError("duplicate stem names (file names must be unique ignoring extension)")

    rates = {s.sample_rate for s in stems}
    if len(rates) != 1:
        detail = ", ".join(f"{s.path.name}={s.sample_rate} Hz" for s in stems)
        raise StemLoadError(
            "sample rate mismatch between stems (edmmix never resamples; "
            f"re-export all stems at one rate): {detail}")

    lengths = {s.audio.shape[0] for s in stems}
    if len(lengths) != 1:
        detail = ", ".join(f"{s.path.name}={s.audio.shape[0]} samples" for s in stems)
        raise StemLoadError(
            "length mismatch between stems (all stems must start at the same point and "
            f"have identical length): {detail}")

    return StemSet(directory, stems[0].sample_rate, stems[0].audio.shape[0], stems)
