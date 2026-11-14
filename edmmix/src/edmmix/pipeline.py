"""Orchestration: ``decide`` (analysis -> parameters) and ``render`` (parameters -> audio).

``mix`` = decide + render. ``render`` never looks at anything but the stems and the
parameter dict, so a saved mix_params.json reproduces the mix bit-for-bit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import analyze, balance, mixbus, params as params_mod, qc, report
from .audioio import dequantize24, quantize24, write_wav24
from .classify import Classifier, classify_stems
from .dsp import filters
from .dsp.util import f64, from_db, rnd
from .loader import StemSet

TONAL_ROLES = {"sub", "bass", "lead", "pad", "pluck_arp", "vocal"}


@dataclass
class RenderResult:
    premaster: np.ndarray                       # float64 (n, 2), after mix-bus gain
    stems: dict[str, np.ndarray]                # final processed stems; they sum to premaster
    mixbus_gain_db: float
    info: dict = field(default_factory=dict)    # render-time measurements (gain reduction etc.)


# ----------------------------------------------------------------------------- render

def check_stems_match(stem_set: StemSet, params: dict) -> None:
    if int(params["sample_rate"]) != stem_set.sample_rate:
        raise params_mod.ParamsError(
            f"params were made for {params['sample_rate']} Hz stems but the folder is "
            f"{stem_set.sample_rate} Hz (sample-based values would be wrong)")
    wanted, have = set(params["stems"]), set(stem_set.names)
    if wanted != have:
        parts = []
        if wanted - have:
            parts.append("missing from folder: " + ", ".join(sorted(wanted - have)))
        if have - wanted:
            parts.append("not in params: " + ", ".join(sorted(have - wanted)))
        raise params_mod.ParamsError("stems folder does not match mix params (" + "; ".join(parts) + ")")


def process_stem(x: np.ndarray, sr: int, sp: dict) -> tuple[np.ndarray, dict]:
    """Per-stem chain that depends on nothing but the stem itself (stage 4)."""
    return x, {}


def interact(name: str, procs: dict[str, np.ndarray], params: dict, sr: int) -> tuple[np.ndarray, dict]:
    """Inter-stem processing for one stem (stage 5)."""
    return procs[name], {}


def apply_bus(x: np.ndarray, bus: dict, sr: int) -> np.ndarray:
    """Bus processing is linear (EQ + gain), so applying it per stem equals applying it to the bus sum."""
    y = filters.apply_sos(x, filters.eq_sos(bus.get("eq", []), sr))
    return y * float(from_db(bus.get("gain_db", 0.0)))


def render_pre_bus(stem_set: StemSet, params: dict) -> tuple[dict[str, np.ndarray], dict]:
    """Everything up to (and including) the per-stem balance gain."""
    sr = stem_set.sample_rate
    names = sorted(params["stems"])
    info: dict = {n: {} for n in names}
    procs = {}
    for name in names:
        procs[name], info[name]["stem_processing"] = process_stem(
            f64(stem_set.get(name).audio), sr, params["stems"][name])
    out = {}
    for name in names:
        y, info[name]["interaction"] = interact(name, procs, params, sr)
        out[name] = y * float(from_db(params["stems"][name]["gain_db"]))
    return out, info


def render(stem_set: StemSet, params: dict) -> RenderResult:
    params_mod.validate(params)
    check_stems_match(stem_set, params)
    sr = stem_set.sample_rate
    pre, info = render_pre_bus(stem_set, params)
    names = sorted(pre)
    bussed = {n: apply_bus(pre[n], params["buses"][params["stems"][n]["bus"]], sr) for n in names}
    del pre
    mix = np.zeros((stem_set.n_samples, 2), dtype=np.float64)
    for name in names:          # fixed summation order -> bit-identical results
        mix += bussed[name]
    gain_db = mixbus.resolve_gain_db(mix, params["mixbus"])
    stems = {n: mixbus.apply_gain(bussed[n], gain_db) for n in names}
    return RenderResult(mixbus.apply_gain(mix, gain_db), stems, gain_db, info)


# ----------------------------------------------------------------------------- analysis

def analyze_stem_set(stem_set: StemSet, manual_roles: dict[str, str] | None = None,
                     bpm_override: float | None = None, classifier: Classifier | None = None) -> dict:
    """Roles + per-stem and global measurements of the raw stems (the ``analyze`` command)."""
    sr = stem_set.sample_rate
    guesses = classify_stems(stem_set, manual_roles, classifier)
    stems = {}
    mix = np.zeros((stem_set.n_samples, 2), dtype=np.float64)
    tonal = np.zeros_like(mix)
    for stem in stem_set.stems:
        guess = guesses[stem.name]
        audio = f64(stem.audio)
        mix += audio
        if guess.role in TONAL_ROLES:
            tonal += audio
        stems[stem.name] = {
            "file": stem.path.name,
            "source_channels": stem.source_channels,
            "source_subtype": stem.subtype,
            "role": guess.role,
            "role_source": guess.source,
            "role_confidence": guess.confidence,
            "role_reason": guess.reason,
            "analysis": analyze.analyze_audio(audio, sr),
        }
    return {
        "input": {"directory": str(stem_set.directory), "sample_rate": sr,
                  "n_samples": stem_set.n_samples, "duration_s": round(stem_set.duration_s, 3),
                  "n_stems": len(stem_set.stems)},
        "global": analyze.analyze_global(mix, tonal, sr, bpm_override),
        "rough_mix": analyze.analyze_audio(mix, sr),
        "stems": stems,
    }


# ----------------------------------------------------------------------------- decide

def decide(stem_set: StemSet, genre: str = "house", reference_path: str | Path | None = None,
           manual_roles: dict[str, str] | None = None, bpm_override: float | None = None,
           classifier: Classifier | None = None) -> tuple[dict, dict]:
    """Analyse the stems and choose every parameter. Returns (params, analysis)."""
    sr = stem_set.sample_rate
    preset = balance.load_preset(genre)
    analysis = analyze_stem_set(stem_set, manual_roles, bpm_override, classifier)
    params = params_mod.new_params(sr, genre)

    tempo = analysis["global"]["tempo"]
    if tempo["bpm"]:
        params["bpm"] = rnd(tempo["bpm"], 3)
        params["bpm_reason"] = f"{tempo['method']} (raw estimate {tempo['raw_bpm']})"
    else:
        params["bpm"] = float(preset["default_bpm"])
        params["bpm_reason"] = f"tempo detection failed; preset default for '{genre}'"

    roles = {}
    for name in sorted(analysis["stems"]):
        entry = analysis["stems"][name]
        roles[name] = entry["role"]
        params["stems"][name] = params_mod.default_stem_params(
            entry["file"], entry["role"],
            f"{entry['role_reason']} [{entry['role_source']}, confidence {entry['role_confidence']:.2f}]")

    procs = {}
    for name in sorted(roles):
        procs[name], _ = process_stem(f64(stem_set.get(name).audio), sr, params["stems"][name])

    loudness = {}
    for name in sorted(roles):
        value = analyze.integrated_lufs(procs[name], sr)
        loudness[name] = float(value) if np.isfinite(value) else None
    for name, decision in balance.decide_gains(loudness, roles, preset).items():
        params["stems"][name]["gain_db"] = decision["gain_db"]
        params["stems"][name]["gain_reason"] = decision["reason"]

    analysis["reference"] = None
    return params_mod.validate(params), analysis


# ----------------------------------------------------------------------------- outputs

def write_outputs(out_dir: str | Path, stem_set: StemSet, params: dict, result: RenderResult,
                  analysis: dict | None, command: str) -> dict:
    """Write premaster.wav, stems_processed/, mix_params.json, report.json and report.md."""
    out_dir = Path(out_dir)
    stems_out = out_dir / "stems_processed"
    stems_out.mkdir(parents=True, exist_ok=True)
    sr = stem_set.sample_rate

    params = params_mod.roundtrip(params)
    params["mixbus"]["gain_db"] = rnd(result.mixbus_gain_db, 4)   # informational in 'auto' mode

    write_wav24(out_dir / "premaster.wav", result.premaster, sr)
    premaster_q = quantize24(result.premaster)
    stems_q = {}
    for name in sorted(result.stems):
        write_wav24(stems_out / params["stems"][name]["file"], result.stems[name], sr)
        stems_q[name] = quantize24(result.stems[name])

    reference_balance = (analysis or {}).get("reference") or {}
    qc_result = qc.run_qc(
        dequantize24(premaster_q), sr, float(params["mixbus"]["target_peak_dbfs"]),
        stems={n: dequantize24(q) for n, q in stems_q.items()},
        null=qc.null_test(premaster_q, stems_q),
        reference_balance=reference_balance.get("band_balance_db"))

    params_mod.save(params, out_dir / "mix_params.json")
    rep = report.build_report(command, stem_set, params, result, analysis, qc_result)
    report.save_report(rep, out_dir)
    return rep


def mix(stem_set: StemSet, out_dir: str | Path, genre: str = "house",
        reference_path: str | Path | None = None, manual_roles: dict[str, str] | None = None,
        bpm_override: float | None = None) -> dict:
    params, analysis = decide(stem_set, genre, reference_path, manual_roles, bpm_override)
    params = params_mod.roundtrip(params)      # render exactly what will be saved
    result = render(stem_set, params)
    return write_outputs(out_dir, stem_set, params, result, analysis, "mix")


def render_from_params(stem_set: StemSet, params: dict, out_dir: str | Path) -> dict:
    result = render(stem_set, params)
    return write_outputs(out_dir, stem_set, params, result, None, "render")
