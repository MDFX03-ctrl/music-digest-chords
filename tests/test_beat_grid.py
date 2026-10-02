import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAVE_AUDIO = all(importlib.util.find_spec(name) for name in ("numpy", "soundfile", "librosa", "scipy"))


def drums_and_bass(folder, bpm, style, seconds=24):
    """Synthetic stems. pop: kick 1+3, snare 2+4, 8th hats. ballad: kick 1, soft snare 2+4, 8th hats."""
    import numpy as np
    import soundfile as sf

    sr = 22050
    rng = np.random.default_rng(1)
    drums, bass = np.zeros(sr * seconds), np.zeros(sr * seconds)
    beat = 60 / bpm

    def add(t, sound):
        i = int(t * sr)
        drums[i:i + len(sound)] += sound[:len(drums) - i]

    def kick(t, v):
        k = np.arange(int(sr * 0.15))
        sweep = 50 + 80 * np.exp(-k / (sr * 0.02))
        sound = v * np.sin(2 * np.pi * np.cumsum(sweep) / sr) * np.exp(-k / (sr * 0.05))
        sound[:int(sr * 0.004)] += 0.5 * v * rng.standard_normal(int(sr * 0.004))
        add(t, sound)

    def noise(t, v, decay, length):
        k = np.arange(int(sr * length))
        add(t, v * rng.standard_normal(len(k)) * np.exp(-k / (sr * decay)))

    k = 0
    while k * beat < seconds - 1:
        t, pos = 0.3 + k * beat, k % 4
        if style == "pop":
            kick(t, 0.7) if pos in (0, 2) else noise(t, 0.5, 0.06, 0.2)
        else:
            if pos == 0:
                kick(t, 0.5)
            if pos in (1, 3):
                noise(t, 0.35, 0.06, 0.2)
        noise(t, 0.08, 0.008, 0.03)
        noise(t + beat / 2, 0.08, 0.008, 0.03)
        k += 1
    for bar in range(int(seconds / beat / 4) + 1):
        freq = 440 * 2 ** (([48, 43, 45, 41][bar % 4] - 12 - 69) / 12)
        i0 = int((0.3 + bar * 4 * beat) * sr)
        i1 = min(int((0.3 + (bar + 1) * 4 * beat) * sr), len(bass))
        if i0 < len(bass):
            bass[i0:i1] = 0.3 * np.sin(2 * np.pi * freq * np.arange(i1 - i0) / sr)
    folder.mkdir(parents=True, exist_ok=True)
    sf.write(folder / "drums.wav", drums, sr)
    sf.write(folder / "bass.wav", bass, sr)


@unittest.skipUnless(HAVE_AUDIO, "numpy, soundfile, librosa and scipy are needed to measure audio")
class TempoLevelTests(unittest.TestCase):
    """The grid must not halve a song with a backbeat, nor double a ballad with 8th-note hats."""

    def measure(self, bpm, style):
        with tempfile.TemporaryDirectory() as tmp:
            stems = Path(tmp) / "stems"
            drums_and_bass(stems, bpm, style)
            out = Path(tmp) / "grid.json"
            subprocess.run([sys.executable, str(ROOT / "tools" / "beat_grid.py"), str(stems), "--out", str(out)],
                           check=True, capture_output=True)
            return json.loads(out.read_text(encoding="utf-8"))["bpm"]

    def test_pop_backbeat_is_not_halved(self):
        self.assertAlmostEqual(120, self.measure(120, "pop"), delta=0.1)

    def test_ballad_hats_are_not_doubled(self):
        self.assertAlmostEqual(70, self.measure(70, "ballad"), delta=0.1)


if __name__ == "__main__":
    unittest.main()
