"""mix_params.json: the complete, editable description of a mix.

``render`` reads nothing but this file and the stems. Keys named ``reason`` /
``*_reason`` / ``info`` are documentation for humans and are ignored by the renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .roles import BUSES, ROLE_TO_BUS, ROLES

SCHEMA_VERSION = 1


class ParamsError(Exception):
    pass


def default_stem_params(file_name: str, role: str, role_reason: str = "") -> dict:
    return {
        "file": file_name,
        "role": role,
        "role_reason": role_reason,
        "bus": ROLE_TO_BUS[role],
        "phase": {"apply": False, "invert_polarity": False, "delay_samples": 0, "reason": "not analysed"},
        "highpass": {"enabled": False, "cutoff_hz": 20.0, "order": 2, "reason": ""},
        "eq": [],
        "compressor": {"enabled": False, "threshold_db": 0.0, "ratio": 1.0, "attack_ms": 10.0,
                       "release_ms": 100.0, "knee_db": 6.0, "makeup_db": 0.0, "oversample": 4, "reason": ""},
        "sidechain": {"enabled": False, "depth_db": 0.0, "attack_ms": 2.0, "hold_ms": 15.0,
                      "release_beats": 0.5, "curve": 2.0, "reason": ""},
        "dynamic_eq": [],
        "gain_db": 0.0,
        "gain_reason": "",
    }


def new_params(sample_rate: int, genre: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "edmmix_version": __version__,
        "sample_rate": int(sample_rate),
        "genre": genre,
        "bpm": 120.0,
        "bpm_reason": "",
        "stems": {},
        "sidechain": {"source_stems": [], "onsets_samples": [], "reason": ""},
        "mono_bass": {"enabled": False, "freq_hz": 120.0, "transition_hz": 60.0, "attenuation_db": 80.0,
                      "reason": ""},
        "buses": {bus: {"gain_db": 0.0, "eq": [], "reason": ""} for bus in BUSES},
        "mixbus": {"target_peak_dbfs": -6.0, "gain_mode": "auto", "gain_db": 0.0,
                   "reason": "gain only; sample peak normalised to the target, no limiter"},
    }


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ParamsError(message)


def validate(params: dict) -> dict:
    _require(isinstance(params, dict), "params must be a JSON object")
    _require(params.get("schema_version") == SCHEMA_VERSION,
             f"unsupported schema_version {params.get('schema_version')!r} (expected {SCHEMA_VERSION})")
    for key in ("sample_rate", "bpm", "stems", "sidechain", "mono_bass", "buses", "mixbus"):
        _require(key in params, f"missing top-level key '{key}'")
    _require(float(params["bpm"]) > 0, "bpm must be positive")
    _require(isinstance(params["stems"], dict) and params["stems"], "'stems' must be a non-empty object")
    for name, sp in params["stems"].items():
        _require(sp.get("role") in ROLES, f"stem '{name}': unknown role {sp.get('role')!r}")
        _require(sp.get("bus") in params["buses"], f"stem '{name}': unknown bus {sp.get('bus')!r}")
        for key in ("phase", "highpass", "eq", "compressor", "sidechain", "dynamic_eq", "gain_db"):
            _require(key in sp, f"stem '{name}': missing '{key}'")
        comp = sp["compressor"]
        if comp.get("enabled"):
            _require(float(comp["ratio"]) >= 1.0, f"stem '{name}': compressor ratio must be >= 1")
            _require(int(comp.get("oversample", 4)) in (1, 2, 4, 8), f"stem '{name}': oversample must be 1/2/4/8")
        for band in sp["dynamic_eq"]:
            _require(band.get("source") in params["stems"],
                     f"stem '{name}': dynamic_eq source {band.get('source')!r} is not a stem")
            _require(band["source"] != name, f"stem '{name}': dynamic_eq cannot be keyed by itself")
    mixbus = params["mixbus"]
    _require(mixbus.get("gain_mode", "auto") in ("auto", "fixed"), "mixbus.gain_mode must be 'auto' or 'fixed'")
    _require(float(mixbus["target_peak_dbfs"]) <= 0.0, "mixbus.target_peak_dbfs must be <= 0")
    return params


def to_json(params: dict) -> str:
    return json.dumps(params, indent=2, ensure_ascii=False) + "\n"


def roundtrip(params: dict) -> dict:
    """What a reader of the saved file gets back; mix renders from this to guarantee reproducibility."""
    return json.loads(to_json(params))


def save(params: dict, path: str | Path) -> None:
    Path(path).write_text(to_json(params), encoding="utf-8")


def load(path: str | Path) -> dict:
    try:
        params = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParamsError(f"{path}: invalid JSON ({exc})") from exc
    return validate(params)
