"""Write a short original loop so the page and a VST3 can be tried without a song."""

import json
import math
import struct
import wave
from pathlib import Path

SR = 22050


def _write(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for sample in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(frames)


def _add(dest, extra, at):
    for index, sample in enumerate(extra):
        pos = at + index
        if 0 <= pos < len(dest):
            dest[pos] += sample


def _tone(freq, count, volume):
    return [volume * math.sin(2 * math.pi * freq * i / SR) for i in range(count)]


def _click(count, volume):
    return [volume * math.exp(-i / (SR * 0.015)) * (1 if (i // 7) % 2 == 0 else -1) for i in range(count)]


def build(out):
    out = Path(out)
    seconds = 8
    total = SR * seconds
    drums = [0.0] * total
    bass = [0.0] * total
    beat = SR // 2  # 120 BPM, one beat is 0.5 s
    click = _click(int(SR * 0.04), 0.45)
    for step in range(16):
        _add(drums, click if step % 4 == 0 else _click(int(SR * 0.03), 0.22), step * beat)
    for index, freq in enumerate((65.41, 98.00, 110.00, 87.31)):
        _add(bass, _tone(freq, SR * 2, 0.28), index * SR * 2)
    mix = [0.7 * left + 0.9 * right for left, right in zip(drums, bass)]
    _write(out / "stems" / "drums.wav", drums)
    _write(out / "stems" / "bass.wav", bass)
    _write(out / "input.wav", mix)
    chart = "C G Am F"
    track = {
        "title": "Demo loop",
        "artist": "music-digest-chord",
        "key": "C major",
        "keys": [{"t": 0, "key": "C major"}],
        "bpm": 120,
        "beatsPerBar": 4,
        "beats_per_bar": 4,
        "barStart": 0,
        "bar_start": 0,
        "duration": seconds,
        "status": "chords",
        "verified": False,
        "chart_used": True,
        "sections": [{"name": "Intro", "start": 0, "end": seconds}],
        "chords": [
            {"t": 0, "chord": "C", "roman": "I", "conf": "ok", "source": "chart",
             "why": "Loop opens on the tonic; written chart C G Am F starts here."},
            {"t": 2, "chord": "G", "roman": "V", "conf": "ok", "source": "chart",
             "why": "Second token of the written chart, a fifth above the tonic."},
            {"t": 4, "chord": "Am", "roman": "vi", "conf": "ok", "source": "chart",
             "why": "Third token of the written chart, the relative minor."},
            {"t": 6, "chord": "F", "roman": "IV", "conf": "ok", "source": "chart",
             "why": "Fourth token of the written chart, the subdominant, then it repeats."},
        ],
        "notes": ["Original 8 second loop for trying the page and a VST3. Not a commercial recording."],
        "remeasure": None,
        "bleed_stems": [],
    }
    (out / "track.json").write_text(json.dumps(track, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The demo knows its own chords, so it ships the chart and grid it was named
    # from. Without this the track would claim a chart nobody supplied, and
    # "python -m mdchord check" would rightly reject it.
    measurement = {
        "manifest": {
            "source": "demo",
            "model": "none",
            "stems": [{"kind": kind, "share": 0.5, "rms_db": -18.0, "duration": seconds}
                      for kind in ("drums", "bass")],
        },
        "grid": {"bpm": 120.0, "beat_phase": 0.0, "period": 0.5, "duration": seconds,
                 "windows": [], "change_counts": [4, 0, 0, 0]},
        "bars": {"key": "C major", "tuning_cents": 0.0, "bpm": 120.0, "start": 0.0, "bars": [
            {"bar": index + 1, "t": index * 2.0, "beats": 4, "mix": -18.0, "vox": -120.0,
             "drums": -18.0, "bassdb": -18.0,
             "parts": [{"t": index * 2.0, "bass": name,
                        "low": name, "chroma": []}]}
            for index, name in enumerate(("C", "G", "A", "F"))
        ]},
        "chart": chart,
        "chart_verbatim": True,
        "candidates": None,
        "duration": seconds,
    }
    (out / "measurement.json").write_text(json.dumps(measurement, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "analysis.md").write_text(
        "# Demo loop\n\n**Status:** ⏳ for trying the player.\n\n"
        "### 2. Chord map\n\n| Section | Chords |\n|---|---|\n| Intro | C G Am F |\n",
        encoding="utf-8",
    )
    return out
