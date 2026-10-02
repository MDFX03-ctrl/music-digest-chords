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
        "sections": [{"name": "Intro", "start": 0, "end": seconds}],
        "chords": [
            {"t": 0, "chord": "C", "roman": "I", "conf": "ok", "source": "chart"},
            {"t": 2, "chord": "G", "roman": "V", "conf": "low", "source": "chart",
             "options": [{"chord": "G", "roman": "V"}, {"chord": "G7", "roman": "V7"}]},
            {"t": 4, "chord": "Am", "roman": "vi", "conf": "ok", "source": "chart"},
            {"t": 6, "chord": "F", "roman": "IV", "conf": "ok", "source": "chart"},
        ],
        "notes": ["Original 8 second loop for trying the page and a VST3. Not a commercial recording."],
    }
    (out / "track.json").write_text(json.dumps(track, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "analysis.md").write_text(
        "# Demo loop\n\n**Status:** ⏳ for trying the player.\n\n"
        "### 2. Chord map\n\n| Section | Chords |\n|---|---|\n| Intro | C G Am F |\n",
        encoding="utf-8",
    )
    return out
