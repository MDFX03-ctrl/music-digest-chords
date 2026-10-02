import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdchord.config import Config
from mdchord.options import attach_options
from mdchord.packet import remeasure_plan
from mdchord.pipeline import DigestError, digest
from mdchord.reason import messages
from mdchord.validate import extract_json, validate

BARS = {
    "key": "D major",
    "bpm": 75,
    "start": 0.5,
    "bars": [
        {"bar": 1, "t": 0.5, "beats": 4, "parts": [
            {"t": 0.5, "bass": "G", "low": "G", "chroma": ["D", "A", "G", "B"]},
            {"t": 2.1, "bass": "A", "low": "A", "chroma": ["D", "A", "E", "G"]},
        ]},
        {"bar": 2, "t": 3.7, "beats": 4, "parts": [
            {"t": 3.7, "bass": "B", "low": "B", "chroma": ["D", "A", "B", "F#"]},
        ]},
    ],
}
GRID = {"bpm": 75, "beat_phase": 0.5, "duration": 6.9, "change_counts": [1, 0, 1, 0]}
MEAS = {
    "manifest": {"stems": [{"kind": "bass", "share": 0.4}]},
    "grid": GRID,
    "bars": BARS,
    "chart": "G A Bm",
    "chart_verbatim": True,
    "candidates": None,
    "duration": 6.9,
}


def chords_reply():
    return {
        "status": "chords",
        "key": "D major",
        "bpm": 75,
        "bar_start": 0.5,
        "beats_per_bar": 4,
        "chart_used": True,
        "sections": [{"name": "Intro", "start": 0.5, "end": 6.9}],
        "chords": [
            {"t": 0.5, "chord": "G", "roman": "IV", "conf": "ok", "source": "chart",
             "bass_pc": "G", "alternative": None, "why": "Bass G matches chart G. Chroma D/A is a drone.", "options": None},
            {"t": 2.1, "chord": "A", "roman": "V", "conf": "ok", "source": "chart",
             "bass_pc": "A", "alternative": None, "why": "Bass A matches chart A. The D/A chroma is still the drone.", "options": None},
        ],
        "remeasure": None,
        "bleed_stems": [],
        "notes": [],
    }


class ValidateTests(unittest.TestCase):
    def test_accepts_chart_chords_and_snaps_time(self):
        raw = chords_reply()
        raw["chords"][0]["t"] = 0.52
        cleaned, errors = validate(raw, MEAS)
        self.assertEqual(errors, [], errors)
        self.assertEqual(cleaned["chords"][0]["t"], 0.5)
        self.assertEqual(cleaned["bpm"], 75)

    def test_rejects_chroma_only_confidence(self):
        raw = chords_reply()
        raw["chords"][0]["source"] = "measured"
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("conf ok" in item for item in errors), errors)

    def test_rejects_invented_time(self):
        raw = chords_reply()
        raw["chords"][1]["t"] = 9.9
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("not a bar or part time" in item for item in errors), errors)

    def test_rejects_alternative_without_candidates(self):
        raw = chords_reply()
        raw["chords"][0]["alternative"] = "Gmaj7"
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("alternative requires candidates" in item for item in errors), errors)

    def test_fence_and_prose(self):
        text = "Here is the map:\n```json\n" + json.dumps(chords_reply()) + "\n```"
        self.assertEqual(extract_json(text)["status"], "chords")

    def test_remeasure_must_name_a_grid_time(self):
        raw = {
            "status": "needs_remeasure", "chords": [], "sections": [],
            "remeasure": {"bar_start": 8, "short_bars": [{"bar": 2, "beats": 2}], "reason": "Fill at bar 2."},
        }
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("bar_start" in item for item in errors), errors)

    def test_nc_symbol(self):
        raw = chords_reply()
        raw["chords"][1].update({"chord": "N.C.", "roman": "N.C.", "conf": "low", "source": "measured",
                                  "why": "No bass and no harmonic stem in this part."})
        _, errors = validate(raw, MEAS)
        self.assertEqual(errors, [], errors)


class OptionTests(unittest.TestCase):
    def test_options_come_from_scores(self):
        chords = [{"chord": "A", "roman": "V", "conf": "low", "options": None}]
        attach_options(chords, {"0": {"candidates": [
            {"chord": "A", "score": 0.4, "bass_ok": True},
            {"chord": "A7sus4", "score": 0.8, "bass_ok": True},
            {"chord": "D", "score": 0.9, "bass_ok": False},
        ]}})
        self.assertEqual([item["chord"] for item in chords[0]["options"]], ["A", "A7sus4"])

    def test_empty_remeasure_plan(self):
        self.assertIsNone(remeasure_plan({"bar_start": 0.5, "reason": "x"}, 0.5, 2))
        self.assertEqual(remeasure_plan({"bar_start": 2.1, "short_bars": [{"bar": 21, "beats": 2}]}, 0.5, 2)[2], ["21:2"])


class MessageTests(unittest.TestCase):
    def test_repair_wrapper_is_data(self):
        packet = {"chart": "G"}
        wrapped = json.loads(messages("rules", packet, ["bpm does not match"])[1]["content"])
        self.assertEqual(wrapped["validation_errors"], ["bpm does not match"])
        self.assertEqual(wrapped["measurement"]["chart"], "G")


class FakeEngine:
    def __init__(self):
        self.starts = []
        self.stem_calls = 0

    def stems(self, src, out, model="htdemucs_6s"):
        self.stem_calls += 1
        out = Path(out)
        (out / "stems").mkdir(parents=True, exist_ok=True)
        (out / "input.wav").write_bytes(b"RIFF")
        (out / "manifest.json").write_text(json.dumps({
            "source": str(src), "model": model,
            "stems": [{"kind": "bass", "share": 0.4, "rms_db": -18, "duration": 6.9}],
        }), encoding="utf-8")

    def grid(self, stems, dest, bpm_min=60, bpm_max=140):
        Path(dest).write_text(json.dumps(GRID), encoding="utf-8")

    def bars(self, stems, mix, bpm, start, dest, beats=4, split=2, shorts=()):
        self.starts.append((float(start), int(split), tuple(shorts)))
        Path(dest).write_text(json.dumps(BARS), encoding="utf-8")

    def options(self, track, stems, offset, indexes):
        raise AssertionError("options are not scored when every chord is ok")

    def voicings(self, track, stems, offset, dest):
        Path(dest).write_text(json.dumps({"voicings": []}), encoding="utf-8")


class PipelineTests(unittest.TestCase):
    def test_measure_only_does_not_call_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()

            def explode(*_args, **_kwargs):
                raise AssertionError("model was called")

            summary = digest(audio, root / "out", measure_only=True, engine=engine, complete_fn=explode)
            self.assertEqual(summary["status"], "measured")
            self.assertTrue((root / "out" / "measurement.json").is_file())
            self.assertEqual(engine.stem_calls, 1)

    def test_remeasure_then_chords(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            chart = root / "chart.txt"
            chart.write_text("G\nA\nBm\n", encoding="utf-8")
            engine = FakeEngine()
            calls = {"n": 0}

            def complete(measurement, config, errors=None, agents=None, opener=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    return json.dumps({
                        "status": "needs_remeasure", "chords": [], "sections": [],
                        "remeasure": {"bar_start": 2.1, "short_bars": [{"bar": 2, "beats": 2}],
                                      "reason": "The pattern starts on the next bass note, after a drum fill."},
                    })
                self.assertIsNone(errors)
                return json.dumps(chords_reply())

            summary = digest(
                audio, root / "out", chart=chart, title="Song", artist="A",
                config=Config("http://example/v1", "key", "model"),
                engine=engine, complete_fn=complete,
            )
            self.assertEqual(summary["status"], "chords")
            self.assertEqual(summary["chords"], 2)
            self.assertEqual(engine.starts[0][0], 0.5)
            self.assertEqual(engine.starts[1][0], 2.1)
            self.assertEqual(engine.starts[1][2], ("2:2",))
            track = json.loads((root / "out" / "track.json").read_text(encoding="utf-8"))
            self.assertEqual(track["chords"][0]["chord"], "G")
            self.assertIn("⏳", (root / "out" / "analysis.md").read_text(encoding="utf-8"))

    def test_missing_api_does_not_start_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()
            with self.assertRaises(DigestError):
                digest(audio, root / "out", engine=engine, config=Config("http://example/v1", "", ""))
            self.assertEqual(engine.stem_calls, 0)


if __name__ == "__main__":
    unittest.main()
