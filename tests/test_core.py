import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mdchord.__main__ import main
from mdchord.pipeline import DigestError, digest
from mdchord.validate import validate

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
        "duration": 6.9,
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
        self.assertTrue(any("alternative is not a candidate" in item for item in errors), errors)

    def test_symbol_grammar(self):
        from mdchord.validate import check_symbol
        good = ["C", "Am", "F#m7b5", "Bbmaj7", "G7sus4", "Ddim7", "Eaug", "Cadd9", "Cm6", "C7#9",
                "Fmaj7#11", "G13b9", "D/F#", "C6/A", "Ebm9", "N.C."]
        bad = ["Cmm", "C7777", "Cmaj", "Csus", "C7b9b9", "Cm7m", "H", "C/H", "C?", " C", "Cxyz", "C69"]
        for symbol in good:
            self.assertTrue(check_symbol(symbol), symbol)
        for symbol in bad:
            self.assertFalse(check_symbol(symbol), symbol)

    def test_options_need_candidates_at_that_time(self):
        raw = chords_reply()
        raw["chords"][0].update(conf="low", options=[{"chord": "G"}, {"chord": "Gmaj7"}])
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("options need candidates" in item for item in errors), errors)
        # Scored at another time does not count.
        elsewhere = dict(MEAS, candidates={"2.1": [{"chord": "Gmaj7", "score": 0.7, "bass_ok": True}]})
        _, errors = validate(raw, elsewhere)
        self.assertTrue(any("options need candidates" in item for item in errors), errors)

    def test_options_saved_by_the_scoring_tools_pass(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from save_candidates import save
        raw = chords_reply()
        raw["chords"][0].update(conf="low", options=[{"chord": "G"}, {"chord": "Gmaj7"}])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "measurement.json"
            path.write_text(json.dumps(MEAS), encoding="utf-8")
            save(path, {0.5: [{"chord": "Gmaj7", "score": 0.7, "bass_ok": True}]})
            save(path, {0.50: [{"chord": "Em/G", "score": 0.6, "bass_ok": True}]})
            measured = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(["Gmaj7", "Em/G"], [row["chord"] for row in measured["candidates"]["0.5"]])
        _, errors = validate(raw, measured)
        self.assertEqual(errors, [], errors)
        raw["chords"][0]["options"][1]["chord"] = "Gsus4"
        _, errors = validate(raw, measured)
        self.assertTrue(any("neither the chord nor a candidate" in item for item in errors), errors)

    def test_remeasure_must_name_a_grid_time(self):
        raw = {
            "status": "needs_remeasure", "chords": [], "sections": [],
            "remeasure": {"bar_start": 8, "short_bars": [{"bar": 2, "beats": 2}], "reason": "Fill at bar 2."},
        }
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("bar_start" in item for item in errors), errors)

    def test_rejects_chords_out_of_time_order(self):
        raw = chords_reply()
        raw["chords"].reverse()
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("time order" in item for item in errors), errors)
        raw = chords_reply()
        raw["chords"][1]["t"] = 0.52   # snaps onto the first chord's time
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("one event per time" in item for item in errors), errors)

    def test_the_first_chord_starts_at_bar_start(self):
        raw = chords_reply()
        del raw["chords"][0]
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("first chord" in item for item in errors), errors)

    def test_the_page_keys_must_agree_with_the_checked_ones(self):
        raw = chords_reply()
        del raw["duration"]
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("duration is missing" in item for item in errors), errors)
        raw = chords_reply()
        raw.update(duration=9.9, barStart=0.0, beatsPerBar=3)
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("duration does not match" in item for item in errors), errors)
        self.assertTrue(any("barStart" in item for item in errors), errors)
        self.assertTrue(any("beatsPerBar" in item for item in errors), errors)
        raw = chords_reply()
        raw.update(barStart=0.5, beatsPerBar=4)
        _, errors = validate(raw, MEAS)
        self.assertEqual(errors, [], errors)

    def test_sections_start_on_bar_lines(self):
        raw = chords_reply()
        # 2.1 is a part time inside bar 1, not a bar line.
        raw["sections"] = [{"name": "Intro", "start": 0.5, "end": 2.1}, {"name": "V1", "start": 2.1, "end": 6.9}]
        _, errors = validate(raw, MEAS)
        self.assertTrue(any("bar line" in item for item in errors), errors)
        raw["sections"] = [{"name": "Intro", "start": 0.5, "end": 3.7}, {"name": "V1", "start": 3.7, "end": 6.9}]
        _, errors = validate(raw, MEAS)
        self.assertEqual(errors, [], errors)

    def test_a_measurement_without_grid_bpm_is_reported_not_a_crash(self):
        raw = chords_reply()
        _, errors = validate(raw, dict(MEAS, grid={"duration": 6.9}))
        self.assertTrue(any("grid.bpm" in item for item in errors), errors)

    def test_nc_symbol(self):
        raw = chords_reply()
        raw["chords"][1].update({"chord": "N.C.", "roman": "N.C.", "conf": "low", "source": "measured",
                                  "why": "No bass and no harmonic stem in this part."})
        _, errors = validate(raw, MEAS)
        self.assertEqual(errors, [], errors)


class CheckTests(unittest.TestCase):
    """The check command is how a hand-written track.json is verified."""

    def _song(self, root, track, measurement=None):
        song = root / "song"
        song.mkdir()
        (song / "track.json").write_text(json.dumps(track), encoding="utf-8")
        if measurement is not None:
            (song / "measurement.json").write_text(json.dumps(measurement), encoding="utf-8")
        return song

    def test_a_spec_shaped_track_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            song = self._song(Path(tmp), chords_reply(), MEAS)
            self.assertEqual(main(["check", str(song)]), 0)

    def test_an_unparseable_chord_symbol_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = chords_reply()
            track["chords"][0]["chord"] = "G??? "
            song = self._song(Path(tmp), track, MEAS)
            self.assertEqual(main(["check", str(song)]), 1)

    def test_a_measured_chord_cannot_be_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = chords_reply()
            track["chords"][1].update({"conf": "ok", "source": "measured"})
            song = self._song(Path(tmp), track, MEAS)
            self.assertEqual(main(["check", str(song)]), 1)

    def test_check_without_measurement_still_reads_the_track(self):
        # No measurement.json: times and bpm are not cross-checked, but the
        # rules that need no grid (symbols, conf/source pairing) still apply.
        with tempfile.TemporaryDirectory() as tmp:
            track = {
                "status": "chords", "key": "C major", "bpm": 120, "bar_start": 0,
                "beats_per_bar": 4, "chart_used": False,
                "sections": [{"name": "Intro", "start": 0, "end": 4}],
                "duration": 4,
                "chords": [{"t": 0, "chord": "C", "roman": "I", "conf": "low", "source": "measured",
                            "why": "Bass C, no chart."}],
                "remeasure": None, "bleed_stems": [], "notes": [],
            }
            song = self._song(Path(tmp), track)
            self.assertEqual(main(["check", str(song)]), 0)

            track["chords"][0]["chord"] = "C//G"
            (song / "track.json").write_text(json.dumps(track), encoding="utf-8")
            self.assertEqual(main(["check", str(song)]), 1)

    def test_missing_track_reports_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            self.assertEqual(main(["check", str(empty)]), 1)

    def test_a_track_saved_with_a_bom_still_parses(self):
        # Notepad on Windows writes a UTF-8 BOM. A song folder must not fail
        # with "Unexpected UTF-8 BOM" because of how the file was saved.
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp) / "song"
            song.mkdir()
            body = json.dumps(chords_reply())
            (song / "measurement.json").write_text(json.dumps(MEAS), encoding="utf-8")
            (song / "track.json").write_text(body, encoding="utf-8-sig")
            self.assertTrue((song / "track.json").read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(main(["check", str(song)]), 0)

            # And a bad symbol is still caught, not excused by the BOM.
            (song / "track.json").write_text(
                body.replace('"chord": "G"', '"chord": "G??"'), encoding="utf-8-sig")
            self.assertEqual(main(["check", str(song)]), 1)


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


class PipelineTests(unittest.TestCase):
    def test_digest_writes_the_measurement_and_no_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()
            summary = digest(audio, root / "out", engine=engine)
            self.assertEqual(summary["status"], "measured")
            out = root / "out"
            self.assertTrue((out / "measurement.json").is_file())
            self.assertTrue((out / "grid.json").is_file())
            self.assertTrue((out / "bars.json").is_file())
            self.assertEqual(engine.stem_calls, 1)
            # Naming is the caller's job now, so digest must not invent a track.
            self.assertFalse((out / "track.json").exists())

    def test_digest_uses_the_grid_phase_for_the_downbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()
            digest(audio, root / "out", engine=engine)
            self.assertEqual(engine.starts[0][0], 0.5)

    def test_short_bars_reach_the_bar_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()
            digest(audio, root / "out", shorts=["21:2", "40:6"], engine=engine)
            self.assertEqual(engine.starts[0][2], ("21:2", "40:6"))
            with self.assertRaises(DigestError):
                digest(audio, root / "out", shorts=["21"], engine=FakeEngine())
            with self.assertRaises(DigestError):
                digest(audio, root / "out", shorts=["0:2"], engine=FakeEngine())

    def test_the_command_line_passes_short_bars_through(self):
        import mdchord.__main__ as cli
        seen = {}

        def fake_digest(audio, out, **kwargs):
            seen.update(kwargs)
            return {"status": "measured", "out": out}

        old = cli.digest
        cli.digest = fake_digest
        try:
            self.assertEqual(main(["digest", "song.wav", "--out", "x", "--short", "21:2", "--short", "40:6"]), 0)
        finally:
            cli.digest = old
        self.assertEqual(seen["shorts"], ["21:2", "40:6"])

    def test_a_missing_audio_file_is_refused_before_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = FakeEngine()
            with self.assertRaises(DigestError):
                digest(root / "nope.wav", root / "out", engine=engine)
            self.assertEqual(engine.stem_calls, 0)
            self.assertFalse((root / "out").exists())

    def test_a_missing_chart_file_is_refused_before_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            engine = FakeEngine()
            with self.assertRaises(DigestError):
                digest(audio, root / "out", chart="C G Am F", engine=engine)
            self.assertEqual(engine.stem_calls, 0)

    def test_chart_title_and_artist_reach_the_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.wav"
            audio.write_bytes(b"audio")
            chart = root / "chart.txt"
            chart.write_text("G A Bm\n", encoding="utf-8-sig")
            digest(audio, root / "out", chart=str(chart), title="星", artist="A", engine=FakeEngine())
            measured = json.loads((root / "out" / "measurement.json").read_text(encoding="utf-8"))
        self.assertEqual("G A Bm", measured["chart"])
        self.assertTrue(measured["chart_verbatim"])
        self.assertEqual(("星", "A"), (measured["title"], measured["artist"]))

    def test_demo_runs_without_a_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["demo", "--out", str(Path(tmp) / "d")]), 0)


if __name__ == "__main__":
    unittest.main()
