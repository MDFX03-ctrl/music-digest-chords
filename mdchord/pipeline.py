"""One digest: separate the stems, measure the grid and the bars, write the packet.

Naming the chords is not done here. No model is called. The measurement this
writes is what you name from, following prompts/chord-naming.md.
"""

import json
from pathlib import Path

from mdchord.engine import Engine
from mdchord.packet import load_json, measurement


class DigestError(RuntimeError):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = list(errors)


def _write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(
    audio,
    out,
    chart=None,
    title=None,
    artist="",
    bar_start=None,
    split=2,
    beats=4,
    bpm_min=60,
    bpm_max=140,
    model_name="htdemucs_6s",
    reuse_stems=False,
    engine=None,
):
    audio = Path(audio)
    dest = Path(out)
    if not audio.is_file():
        raise DigestError([f"audio file not found: {audio}"])
    chart_text = ""
    if chart:
        try:
            chart_text = Path(chart).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise DigestError([f"chart file not readable: {chart} ({exc.strerror or exc})"]) from exc
    dest.mkdir(parents=True, exist_ok=True)

    tool = engine or Engine()
    stems = dest / "stems"
    have_stems = reuse_stems and (dest / "manifest.json").is_file() and stems.is_dir()
    if not have_stems:
        tool.stems(audio, dest, model_name)
    manifest = load_json(dest / "manifest.json")
    tool.grid(stems, dest / "grid.json", bpm_min, bpm_max)
    grid = load_json(dest / "grid.json")
    start = float(grid["beat_phase"] if bar_start is None else bar_start)

    mix = dest / "input.wav"
    tool.bars(stems, mix, grid["bpm"], start, dest / "bars.json", beats, split, ())
    bars = load_json(dest / "bars.json")
    duration = float(grid.get("duration") or 0)
    packet = measurement(manifest, grid, bars, chart_text, duration)
    # Kept so track.json can copy them; check does not read them.
    packet["title"] = title or audio.stem
    packet["artist"] = artist
    _write(dest / "measurement.json", packet)
    # track.json is written by hand from this packet, then checked with
    # "python -m mdchord check". Nothing here names a chord.
    return {
        "status": "measured",
        "out": str(dest),
        "title": title or audio.stem,
        "artist": artist,
        "bpm": grid.get("bpm"),
        "bar_start": start,
        "duration": duration,
    }
