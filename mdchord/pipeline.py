"""One digest: measure, ask the model, validate, then voice the chords."""

import json
import subprocess
from pathlib import Path

from mdchord.config import load_config, missing_api
from mdchord.engine import Engine
from mdchord.options import attach_options
from mdchord.packet import load_json, measurement, remeasure_plan
from mdchord.reason import complete as default_complete
from mdchord.reason import load_agents
from mdchord.report import write_analysis
from mdchord.validate import extract_json, validate


class DigestError(RuntimeError):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = list(errors)


def _write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _track(cleaned, title, artist, audio, duration):
    return {
        "title": title,
        "artist": artist,
        "source_audio": str(audio),
        "status": cleaned["status"],
        "key": cleaned.get("key"),
        "keys": cleaned.get("keys") or [],
        "bpm": cleaned.get("bpm"),
        "beats_per_bar": cleaned.get("beats_per_bar"),
        "beatsPerBar": cleaned.get("beats_per_bar"),
        "bar_start": cleaned.get("bar_start"),
        "barStart": cleaned.get("bar_start"),
        "duration": duration,
        "sections": cleaned.get("sections") or [],
        "chords": cleaned.get("chords") or [],
        "chart_used": cleaned.get("chart_used"),
        "bleed_stems": cleaned.get("bleed_stems") or [],
        "notes": list(cleaned.get("notes") or []),
        "verified": False,
    }


def _ask(packet, config, complete_fn, agents, dest, attempt):
    text = complete_fn(packet, config, None, agents)
    (dest / f"model-{attempt}.txt").write_text(text, encoding="utf-8")
    try:
        parsed = extract_json(text)
        cleaned, errors = validate(parsed, packet)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        cleaned, errors = {}, [f"output is not JSON: {exc}"]
    if not errors:
        return cleaned
    repair = complete_fn(packet, config, errors, agents)
    (dest / f"model-{attempt}-repair.txt").write_text(repair, encoding="utf-8")
    try:
        parsed = extract_json(repair)
    except json.JSONDecodeError as exc:
        raise DigestError([f"repair output is not JSON: {exc}"]) from exc
    cleaned, errors = validate(parsed, packet)
    if errors:
        _write(dest / "errors.json", errors)
        raise DigestError(errors)
    return cleaned


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
    measure_only=False,
    reuse_stems=False,
    config=None,
    engine=None,
    complete_fn=None,
):
    audio = Path(audio)
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    if not audio.is_file():
        raise DigestError([f"audio file not found: {audio}"])
    cfg = config or load_config()
    if not measure_only and missing_api(cfg):
        names = ", ".join(missing_api(cfg))
        raise DigestError([f"Set {names} before the model call. Stem separation has not started."])

    tool = engine or Engine()
    stems = dest / "stems"
    have_stems = reuse_stems and (dest / "manifest.json").is_file() and stems.is_dir()
    if not have_stems:
        tool.stems(audio, dest, model_name)
    manifest = load_json(dest / "manifest.json")
    tool.grid(stems, dest / "grid.json", bpm_min, bpm_max)
    grid = load_json(dest / "grid.json")
    start = float(grid["beat_phase"] if bar_start is None else bar_start)
    chart_text = Path(chart).read_text(encoding="utf-8") if chart else ""
    title = title or audio.stem
    ask = complete_fn or default_complete
    agents = None if measure_only else load_agents()
    mix = dest / "input.wav"
    packet, cleaned = _bars_and_maybe_ask(
        tool, stems, mix, grid, manifest, chart_text, dest, start, split, (),
        beats, measure_only, cfg, ask, agents, 1,
    )
    if measure_only:
        return {"status": "measured", "out": str(dest), "bpm": grid.get("bpm"), "bar_start": start}
    if cleaned["status"] == "needs_remeasure":
        plan = remeasure_plan(cleaned.get("remeasure"), start, split)
        if plan is None:
            _write(dest / "track.json", _track(cleaned, title, artist, audio, packet["duration"]))
            raise DigestError(["the model asked for a remeasure but did not change the grid"])
        start, split, shorts = plan
        packet, cleaned = _bars_and_maybe_ask(
            tool, stems, mix, grid, manifest, chart_text, dest, start, split, shorts,
            beats, False, cfg, ask, agents, 2,
        )

    duration = packet["duration"]
    track = _track(cleaned, title, artist, audio, duration)
    _write(dest / "track.json", track)
    if cleaned["status"] != "chords":
        return {"status": cleaned["status"], "out": str(dest), "key": cleaned.get("key"), "chords": 0}

    indexes = [
        i for i, chord in enumerate(track["chords"])
        if chord.get("conf") == "low" and chord.get("chord") not in (None, "", "N.C.")
    ]
    if indexes:
        try:
            scored = tool.options(dest / "track.json", stems, 0, indexes)
            _write(dest / "candidates.json", scored)
            attach_options(track["chords"], scored)
            _write(dest / "track.json", track)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError) as exc:
            track["notes"].append(f"Option scoring failed: {exc}")
            _write(dest / "track.json", track)
    try:
        tool.voicings(dest / "track.json", stems, 0, dest / "voicings.json")
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        track["notes"].append(f"Voicing measurement failed: {exc}")
        _write(dest / "track.json", track)

    chart_name = str(chart) if chart else None
    (dest / "analysis.md").write_text(
        write_analysis(track, packet["bars"].get("bars") or [], title, artist, chart_name) + "\n",
        encoding="utf-8",
    )
    low = sum(1 for chord in track["chords"] if chord.get("conf") == "low")
    return {
        "status": "chords",
        "out": str(dest),
        "key": track["key"],
        "bpm": track["bpm"],
        "bar_start": track["bar_start"],
        "chords": len(track["chords"]),
        "low": low,
    }


def _bars_and_maybe_ask(tool, stems, mix, grid, manifest, chart_text, dest, start, split, shorts, beats, measure_only, cfg, ask, agents, attempt):
    tool.bars(stems, mix, grid["bpm"], start, dest / "bars.json", beats, split, shorts)
    bars = load_json(dest / "bars.json")
    duration = float(grid.get("duration") or 0)
    packet = measurement(manifest, grid, bars, chart_text, duration)
    _write(dest / "measurement.json", packet)
    if measure_only:
        return packet, None
    cleaned = _ask(packet, cfg, ask, agents, dest, attempt)
    return packet, cleaned
