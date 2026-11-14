"""report.json / report.md: what was measured, what was decided and why, and the QC verdict."""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__


def _fmt(value, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}{unit}"


def decisions_from_params(params: dict) -> list[dict]:
    """Flatten the parameter tree into a list of human-readable decisions with reasons."""
    out: list[dict] = []

    def add(stage: str, target: str, decision: str, reason: str) -> None:
        out.append({"stage": stage, "target": target, "decision": decision, "reason": reason or ""})

    add("analyze", "global", f"BPM {params['bpm']:g}", params.get("bpm_reason", ""))
    for name in sorted(params["stems"]):
        sp = params["stems"][name]
        add("classify", name, f"role '{sp['role']}' -> bus '{sp['bus']}'", sp.get("role_reason", ""))
        hp = sp["highpass"]
        add("stem_processing", name,
            f"high-pass {hp['cutoff_hz']:g} Hz, {6 * int(hp['order'])} dB/oct" if hp["enabled"] else "no high-pass",
            hp.get("reason", ""))
        for band in sp["eq"]:
            add("stem_processing", name,
                f"EQ {band.get('type', 'peak')} {band['freq_hz']:g} Hz {band['gain_db']:+.1f} dB Q {band.get('q', 0.707):g}",
                band.get("reason", ""))
        comp = sp["compressor"]
        add("stem_processing", name,
            (f"compressor {comp['ratio']:g}:1 @ {comp['threshold_db']:.1f} dBFS, "
             f"attack {comp['attack_ms']:g} ms, release {comp['release_ms']:g} ms, {comp['oversample']}x oversampling")
            if comp["enabled"] else "no compression", comp.get("reason", ""))
        phase = sp["phase"]
        if phase.get("invert_polarity") or phase.get("delay_samples"):
            what = []
            if phase.get("invert_polarity"):
                what.append("invert polarity")
            if phase.get("delay_samples"):
                what.append(f"delay {phase['delay_samples']} samples")
            add("interaction", name,
                ("APPLIED: " if phase.get("apply") else "SUGGESTED (not applied): ") + ", ".join(what),
                phase.get("reason", ""))
        elif sp["role"] in ("sub", "bass"):
            add("interaction", name, "kick phase alignment: no change", phase.get("reason", ""))
        sc = sp["sidechain"]
        if sc["enabled"]:
            add("interaction", name,
                f"kick side-chain: {sc['depth_db']:g} dB, attack {sc['attack_ms']:g} ms, hold {sc['hold_ms']:g} ms, "
                f"release {sc['release_beats']:g} beat", sc.get("reason", ""))
        for band in sp["dynamic_eq"]:
            add("interaction", name,
                f"dynamic EQ keyed by '{band['source']}': up to -{band['max_cut_db']:g} dB at "
                f"{band['freq_hz']:g} Hz (Q {band['q']:g})", band.get("reason", ""))
        add("balance", name, f"gain {sp['gain_db']:+.2f} dB", sp.get("gain_reason", ""))
    sc = params["sidechain"]
    if sc.get("source_stems"):
        add("interaction", "global", f"{len(sc['onsets_samples'])} kick transients from "
            f"{', '.join(sc['source_stems'])}", sc.get("reason", ""))
    mb = params["mono_bass"]
    add("interaction", "global",
        f"mono below {mb['freq_hz']:g} Hz (linear-phase crossover)" if mb["enabled"] else "no bass mono-ing",
        mb.get("reason", ""))
    for bus in params["buses"]:
        b = params["buses"][bus]
        if b.get("gain_db") or any(band.get("gain_db") for band in b.get("eq", [])):
            eq = ", ".join(f"{band['type']} {band['freq_hz']:g} Hz {band['gain_db']:+.2f} dB"
                           for band in b.get("eq", []) if band.get("gain_db"))
            add("balance", f"bus:{bus}", f"gain {b.get('gain_db', 0.0):+.2f} dB" + (f"; EQ {eq}" if eq else ""),
                b.get("reason", ""))
    mx = params["mixbus"]
    add("mixbus", "global",
        f"gain {mx['gain_db']:+.2f} dB ({mx.get('gain_mode', 'auto')}) for a {mx['target_peak_dbfs']:g} dBFS peak",
        mx.get("reason", ""))
    return out


def build_report(command: str, stem_set, params: dict, result, analysis: dict | None, qc_result: dict) -> dict:
    rep = {
        "edmmix_version": __version__,
        "command": command,
        "input": (analysis or {}).get("input") or {
            "directory": str(stem_set.directory), "sample_rate": stem_set.sample_rate,
            "n_samples": stem_set.n_samples, "duration_s": round(stem_set.duration_s, 3),
            "n_stems": len(stem_set.stems)},
        "genre": params.get("genre"),
        "global": (analysis or {}).get("global"),
        "reference": (analysis or {}).get("reference"),
        "stems": (analysis or {}).get("stems"),
        "decisions": decisions_from_params(params),
        "render": {"mixbus_gain_db": round(result.mixbus_gain_db, 4), "stems": result.info},
        "qc": qc_result,
        "warnings": list(qc_result["warnings"]),
    }
    return rep


def analysis_markdown(analysis: dict) -> list[str]:
    lines = []
    glob = analysis.get("global")
    if glob:
        tempo, key = glob["tempo"], glob["key"]
        lines += ["## Global analysis", "",
                  f"- **Tempo:** {tempo['bpm']} BPM ({tempo['method']})",
                  f"- **Key:** {key['key']} (confidence {key['confidence']})",
                  "- **Sections:** " + ", ".join(
                      f"{s['label']} {s['start_s']:.1f}-{s['end_s']:.1f} s" for s in glob["sections"]), ""]
    stems = analysis.get("stems")
    if stems:
        lines += ["## Stems (raw input)", "",
                  "| Stem | Role | LUFS-I | Max LUFS-S | True peak | Crest | Corr. |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for name in sorted(stems):
            a = stems[name]["analysis"]
            lines.append(f"| {name} | {stems[name]['role']} | {_fmt(a['integrated_lufs'])} | "
                         f"{_fmt(a['short_term_lufs_max'])} | {_fmt(a['true_peak_dbtp'])} | "
                         f"{_fmt(a['crest_factor_db'])} | {_fmt(a['stereo_correlation'], digits=2)} |")
        lines.append("")
    return lines


def render_markdown(rep: dict) -> str:
    inp = rep["input"]
    lines = [f"# edmmix report ({rep['command']})", "",
             f"- **Input:** `{inp['directory']}` - {inp['n_stems']} stems, {inp['sample_rate']} Hz, "
             f"{inp['duration_s']:.1f} s",
             f"- **Genre preset:** {rep.get('genre')}",
             f"- **edmmix:** {rep['edmmix_version']}", ""]

    qc = rep["qc"]
    lines += ["## QC", "", f"**Result: {'PASS' if qc['passed'] else 'WARNINGS'}**", ""]
    if qc["warnings"]:
        lines += [f"- :warning: {w}" for w in qc["warnings"]] + [""]
    lines += ["| Check | Value |", "|---|---:|",
              f"| Sample peak | {_fmt(qc['sample_peak_dbfs'], ' dBFS', 2)} (target {qc['target_peak_dbfs']:g}) |",
              f"| True peak | {_fmt(qc['true_peak_dbtp'], ' dBTP', 2)} |",
              f"| Integrated loudness | {_fmt(qc['integrated_lufs'], ' LUFS')} |",
              f"| Max short-term loudness | {_fmt(qc['short_term_lufs_max'], ' LUFS')} |",
              f"| Crest factor | {_fmt(qc['crest_factor_db'], ' dB')} |",
              f"| Stereo correlation | {_fmt(qc['stereo_correlation'], digits=2)} |",
              f"| DC offset (L / R) | {qc['dc_offset'][0]:+.6f} / {qc['dc_offset'][1]:+.6f} |",
              f"| Clipped samples | {qc['clipped_samples']} |"]
    if qc.get("null_test"):
        lines.append(f"| Null test (stems sum - premaster), peak | {qc['null_test']['residual_peak_dbfs']:.1f} dBFS |")
    lines += ["", "| Band | Balance (dB re total) | Reference | Mono-sum loss (dB) |", "|---|---:|---:|---:|"]
    ref = qc.get("reference_band_balance_db") or {}
    for band, loss in qc["mono_compatibility_loss_db"].items():
        lines.append(f"| {band} | {_fmt(qc['band_balance_db'].get(band))} | {_fmt(ref.get(band))} | {loss:.1f} |")
    lines.append("")

    lines += analysis_markdown(rep)

    reference = rep.get("reference")
    if reference:
        lines += ["## Reference matching", "", f"- **File:** `{reference['file']}`",
                  f"- {reference['summary']}", ""]

    lines += ["## Decisions", ""]
    current = None
    by_target: dict[str, list[dict]] = {}
    for d in rep["decisions"]:
        by_target.setdefault(d["target"], []).append(d)
    for target in sorted(by_target, key=lambda t: (t != "global", t.startswith("bus:"), t)):
        if target != current:
            lines += [f"### {target}", ""]
            current = target
        for d in by_target[target]:
            reason = f" - _{d['reason']}_" if d["reason"] else ""
            lines.append(f"- **{d['stage']}**: {d['decision']}{reason}")
        lines.append("")
    return "\n".join(lines)


def save_report(rep: dict, out_dir: str | Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(rep) + "\n", encoding="utf-8")


def analysis_report_markdown(analysis: dict) -> str:
    inp = analysis["input"]
    head = ["# edmmix report (analyze)", "",
            f"- **Input:** `{inp['directory']}` - {inp['n_stems']} stems, {inp['sample_rate']} Hz, "
            f"{inp['duration_s']:.1f} s", ""]
    return "\n".join(head + analysis_markdown(analysis))
