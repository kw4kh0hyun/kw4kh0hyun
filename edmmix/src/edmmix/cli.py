"""Command line interface: edmmix analyze | mix | render."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _roles(args, stems_dir: Path):
    from .classify import load_roles_file

    path = Path(args.roles) if args.roles else stems_dir / "roles.json"
    if args.roles and not path.is_file():
        raise FileNotFoundError(f"roles file not found: {path}")
    return load_roles_file(path) if path.is_file() else None


def _print_summary(rep: dict, out_dir: Path) -> None:
    qc = rep["qc"]
    print(f"premaster: {out_dir / 'premaster.wav'}")
    print(f"  peak {qc['sample_peak_dbfs']} dBFS | true peak {qc['true_peak_dbtp']} dBTP | "
          f"{qc['integrated_lufs']} LUFS | correlation {qc['stereo_correlation']}")
    if qc["warnings"]:
        print(f"QC: {len(qc['warnings'])} warning(s)")
        for warning in qc["warnings"]:
            print(f"  ! {warning}")
    else:
        print("QC: pass")
    print(f"details: {out_dir / 'report.md'}")


def cmd_analyze(args) -> int:
    from . import pipeline, report
    from .loader import load_stems

    stems_dir = Path(args.stems_dir)
    stem_set = load_stems(stems_dir)
    analysis = pipeline.analyze_stem_set(stem_set, _roles(args, stems_dir), args.bpm)
    analysis = {"edmmix_version": __version__, "command": "analyze", **analysis}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    tempo, key = analysis["global"]["tempo"], analysis["global"]["key"]
    print(f"{len(stem_set.stems)} stems, {stem_set.sample_rate} Hz, {stem_set.duration_s:.1f} s | "
          f"{tempo['bpm']} BPM | key {key['key']}")
    for name in sorted(analysis["stems"]):
        entry = analysis["stems"][name]
        a = entry["analysis"]
        print(f"  {name:<24} {entry['role']:<11} {a['integrated_lufs']} LUFS, peak {a['sample_peak_dbfs']} dBFS "
              f"({entry['role_source']})")
    print(f"report: {out_dir / 'report.json'}")
    return 0


def cmd_mix(args) -> int:
    from . import pipeline
    from .loader import load_stems

    stems_dir = Path(args.stems_dir)
    stem_set = load_stems(stems_dir)
    rep = pipeline.mix(stem_set, args.out, genre=args.genre, reference_path=args.reference,
                       manual_roles=_roles(args, stems_dir), bpm_override=args.bpm)
    _print_summary(rep, Path(args.out))
    return 0


def cmd_render(args) -> int:
    from . import params as params_mod, pipeline
    from .loader import load_stems

    stem_set = load_stems(args.stems_dir)
    rep = pipeline.render_from_params(stem_set, params_mod.load(args.params), args.out)
    _print_summary(rep, Path(args.out))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edmmix", description="Deterministic stem mixing engine for EDM (premaster output).")
    parser.add_argument("--version", action="version", version=f"edmmix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="analyse stems only and write report.json")
    p.add_argument("stems_dir")
    p.add_argument("-o", "--out", default=".", help="directory for report.json (default: current directory)")
    p.add_argument("--roles", help="roles.json with manual role assignments (default: <stems_dir>/roles.json)")
    p.add_argument("--bpm", type=float, help="override tempo detection")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("mix", help="analyse, decide parameters and render a premaster")
    p.add_argument("stems_dir")
    p.add_argument("-o", "--out", required=True, help="output directory")
    p.add_argument("--reference", help="reference track (WAV/FLAC) for tone-balance matching")
    p.add_argument("--genre", default="house", help="genre preset (house, melodic_techno, future_bass, dnb)")
    p.add_argument("--roles", help="roles.json with manual role assignments (default: <stems_dir>/roles.json)")
    p.add_argument("--bpm", type=float, help="override tempo detection")
    p.set_defaults(func=cmd_mix)

    p = sub.add_parser("render", help="re-render from an (edited) mix_params.json")
    p.add_argument("stems_dir")
    p.add_argument("--params", required=True, help="mix_params.json")
    p.add_argument("-o", "--out", required=True, help="output directory")
    p.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    from .loader import StemLoadError
    from .params import ParamsError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (StemLoadError, ParamsError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
