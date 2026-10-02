"""Command line for one local digest.

  python -m mdchord doctor
  python -m mdchord digest song.wav --chart chart.txt --out songs/song
"""

import argparse
import json
import shutil
import sys

from mdchord.config import load_config
from mdchord.demo import build as build_demo
from mdchord.follower import serve
from mdchord.pipeline import DigestError, digest


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
    cfg = load_config()
    print(f"MDCHORD_BASE_URL: {cfg.base_url}")
    print(f"MDCHORD_MODEL: {cfg.model or 'missing'}")
    print(f"MDCHORD_API_KEY: {'set' if cfg.api_key else 'unused'}")
    print("This pack does not call an API. Name chords from prompts/chord-naming.md.")
    print("VST3, when missing: pip install pedalboard")
    print("Demucs, when missing: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu")
    print("then: pip install -r requirements.txt demucs")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mdchord")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check ffmpeg, node, and local Python packages")

    demo = sub.add_parser("demo", help="Write an 8 second original loop you can open in the player")
    demo.add_argument("--out", default="songs/demo")

    run = sub.add_parser("digest", help="Measure a song locally. Name chords yourself unless you opt into the API")
    run.add_argument("audio")
    run.add_argument("--chart", help="Verbatim chord tokens, one chart, not a summary")
    run.add_argument("--out", required=True, help="Song folder for stems, track.json, and analysis.md")
    run.add_argument("--title", default=None)
    run.add_argument("--artist", default="")
    run.add_argument("--bar-start", type=float, default=None, help="First downbeat in seconds. Default: grid beat phase")
    run.add_argument("--split", type=int, default=2, help="Readings per bar. 2 matches a half-bar harmonic rhythm")
    run.add_argument("--beats", type=int, default=4)
    run.add_argument("--bpm-min", type=float, default=60)
    run.add_argument("--bpm-max", type=float, default=140)
    run.add_argument("--model-stems", default="htdemucs_6s")
    run.add_argument("--measure-only", action="store_true", help="Stems, grid, and bars only. No API")
    run.add_argument("--reuse-stems", action="store_true", help="Skip Demucs when this folder already has stems")
    run.add_argument("--base-url", default=None)
    run.add_argument("--api-key", default=None)
    run.add_argument("--model", default=None, help="Chat model name")

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
            measure_only=args.measure_only,
            reuse_stems=args.reuse_stems,
            config=load_config(args.base_url, args.api_key, args.model),
        )
    except DigestError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "chords":
        print(f"Listen: python -m mdchord serve {args.out}")
    return 0 if summary["status"] in ("chords", "measured") else 2


if __name__ == "__main__":
    sys.exit(main())
