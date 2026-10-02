import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HAVE_AUDIO = all(importlib.util.find_spec(name) for name in ("numpy", "soundfile", "librosa", "scipy"))


@unittest.skipUnless(HAVE_AUDIO, "numpy, soundfile, librosa and scipy are needed to run the tools")
class StemGuardTests(unittest.TestCase):
    """The scoring and voicing tools read the harmonic stems. A song without
    any, such as the demo loop, must get one clear line, not a traceback."""

    def test_tools_say_which_stem_is_missing(self):
        from mdchord.demo import build

        with tempfile.TemporaryDirectory() as tmp:
            song = build(Path(tmp) / "demo")   # drums and bass only
            runs = (
                ("chord_options.py", ["0", "1"]),
                ("score_candidates.py", ["0", '{"1": ["G"]}']),
                ("measure_voicings.py", ["0", str(Path(tmp) / "voicings.json")]),
            )
            for tool, extra in runs:
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / tool), str(song / "track.json"), str(song / "stems"), *extra],
                    capture_output=True, text=True,
                )
                self.assertEqual(proc.returncode, 1, tool)
                self.assertIn("no guitar, piano or other stem", proc.stderr, tool)
                self.assertNotIn("Traceback", proc.stderr, tool)


if __name__ == "__main__":
    unittest.main()
