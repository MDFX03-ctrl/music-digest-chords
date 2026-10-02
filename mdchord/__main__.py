"""Command line for one local digest.

  python -m mdchord doctor
  python -m mdchord digest song.wav --out songs/song
  python -m mdchord check songs/song
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from mdchord.demo import build as build_demo
from mdchord.follower import serve
from mdchord.packet import load_json
from mdchord.pipeline import DigestError, digest
from mdchord.validate import ValidateError, validate


def doctor():
    print(f"python {sys.version.split()[0]}")
    for name in ("ffmpeg", "node"):
        found = shutil.which(name)
        print(f"{name}: {found or 'missing'}")
    for module in ("numpy", "soundfile", "librosa", "demucs", "pedalboard"):
        try:
            __import__(module)
            print(f"{module}: import ok")
        except Exception as exc:
            print(f"{module}: missing ({exc.__class__.__name__})")
    print("This pack does not call an API. Name chords from prompts/chord-naming.md.")
    print("VST3, when missing: pip install pedalboard")
    print("Demucs, when missing: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
    print("then: pip install -r requirements.txt demucs")
    return 0


def _context_from_track(track):
    """Enough measurement for check when the song folder has no measurement.json.

    Without it the time and bpm cross-checks are skipped rather than guessed:
    every chord time stands as written, and there is no chart and no candidate
    list, so a rule that depends on either still fails loudly.
    """
    times = []
    for chord in track.get("chords") or []:
        if isinstance(chord, dict) and chord.get("t") is not None:
            times.append(float(chord["t"]))
    times = sorted(times)
    bars = {"bars": [{"bar": index + 1, "t": value, "beats": track.get("beats_per_bar") or 4}
                     for index, value in enumerate(times)]}
    duration = track.get("duration")
    if duration is None:
        # Fall back to the last section or chord so the section span can still
        # be checked; there is no grid to take it from.
        ends = [float(row["end"]) for row in track.get("sections") or []
                if isinstance(row, dict) and row.get("end") is not None]
        duration = max(ends) if ends else (times[-1] if times else 0)
    return {
        "grid": {"bpm": track.get("bpm"), "duration": duration},
        "bars": bars,
        "chart": None,
        "chart_verbatim": False,
        "candidates": None,
        "duration": duration,
    }


def check(song):
    """Validate a hand-written track.json against prompts/chord-naming.md."""
    folder = Path(song)
    track_path = folder / "track.json"
    if not track_path.is_file():
        raise ValidateError([f"no track.json in {folder}"])
    track = load_json(track_path)
    measured = folder / "measurement.json"
    if measured.is_file():
        context = load_json(measured)
        source = str(measured)
    else:
        context = _context_from_track(track)
        source = "the track itself (no measurement.json, so the grid is not cross-checked)"
    _, errors = validate(track, context)
    return {"track": str(track_path), "checked_against": source, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mdchord")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check ffmpeg, node, and local Python packages")

    demo = sub.add_parser("demo", help="Write an 8 second original loop you can open in the player")
    demo.add_argument("--out", default="songs/demo")

    run = sub.add_parser("digest", help="Measure a song locally. This does not name chords and never calls a model")
    run.add_argument("audio")
    run.add_argument("--chart", help="Verbatim chord tokens, one chart, not a summary")
    run.add_argument("--out", required=True, help="Song folder for stems and the measurement")
    run.add_argument("--title", default=None)
    run.add_argument("--artist", default="")
    run.add_argument("--bar-start", type=float, default=None, help="First downbeat in seconds. Default: grid beat phase")
    run.add_argument("--split", type=int, default=2, help="Readings per bar. 2 matches a half-bar harmonic rhythm")
    run.add_argument("--beats", type=int, default=4)
    run.add_argument("--bpm-min", type=float, default=60)
    run.add_argument("--bpm-max", type=float, default=140)
    run.add_argument("--model-stems", default="htdemucs_6s")
    run.add_argument("--reuse-stems", action="store_true", help="Skip Demucs when this folder already has stems")

    verify = sub.add_parser("check", help="Check a hand-written track.json against the naming spec")
    verify.add_argument("song", help="Song folder that has track.json. measurement.json is used when present")

    listen = sub.add_parser("serve", help="Open Chord Follower for the songs library, or for one song folder")
    listen.add_argument("song", nargs="?", default="songs", help="Library folder, or one folder that contains track.json. Default: songs")
    listen.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        return doctor()
    if args.cmd == "demo":
        dest = build_demo(args.out)
        print(f"Wrote {dest}")
        print(f"Listen: python -m mdchord serve {dest}")
        return 0
    if args.cmd == "check":
        try:
            result = check(args.song)
        except (ValidateError, DigestError) as exc:
            print(exc, file=sys.stderr)
            return 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"checked {result['track']} against {result['checked_against']}")
        if result["errors"]:
            for line in result["errors"]:
                print(f"  - {line}")
            print(f"{len(result['errors'])} problem(s)")
            return 1
        print("no problems")
        return 0
    if args.cmd == "serve":
        try:
            serve(args.song, args.port)
        except DigestError as exc:
            print(exc, file=sys.stderr)
            return 1
        except OSError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    try:
        summary = digest(
            args.audio,
            args.out,
            chart=args.chart,
            title=args.title,
            artist=args.artist,
            bar_start=args.bar_start,
            split=args.split,
            beats=args.beats,
            bpm_min=args.bpm_min,
            bpm_max=args.bpm_max,
            model_name=args.model_stems,
            reuse_stems=args.reuse_stems,
        )
    except DigestError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Name the chords into track.json, then: python -m mdchord check " + args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
