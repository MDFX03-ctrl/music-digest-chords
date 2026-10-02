import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mdchord.follower as follower
import mdchord.vst as vst
from mdchord.demo import build as build_demo
from mdchord.follower import VIEWER, cf_data, make_server
from mdchord.validate import validate


def wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 80)


# A shipped file must not carry an absolute path from the machine that made it.
# Drive letters alone are not proof: a placeholder like "C:\Program Files\Common
# Files\VST3" is a generic Windows location the page may legitimately suggest, so
# that one string is allowlisted explicitly rather than the rule being loosened.
# The GitHub organisation in this project's own URL is public and must stay.
ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\{1,2}\w[\w .-]*")
# The match runs to the first separator, so it yields the drive plus one segment
# ("E:\MDFX03"). That is the part that identifies a machine, and it is enough.
# Only generic Windows locations a UI may legitimately suggest belong here.
ABSOLUTE_PATH_ALLOWED = ("C:\\Program Files", "C:\\Users\\Public")
# A real absolute path has a drive, at least one separator, and more than one
# segment. This drops escapes such as "map:\n" that only look like a drive.
PATH_SCAN_MIN_CHARS = 6
# Only files that a clone actually receives. songs/, the instrument catalog,
# and the caches stay out: see .gitignore. The test sources are left out on
# purpose: fake "C:\..." strings are their fixtures, not a machine path.
PATH_SCAN_TREES = ("mdchord", "tools", "tests", "viewer", "prompts")
PATH_SCAN_SKIP_NAMES = {"test_core.py", "test_follower.py"}
PATH_SCAN_FILES = (
    ".gitattributes",
    ".gitignore",
    "README.md",
    "AGENTS.md",
    "THIRD-PARTY.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.txt",
    "start-follower.bat",
    "songs/README.md",
)
PATH_SCAN_SUFFIXES = (".md", ".py", ".js", ".bat", ".toml", ".txt", ".html", ".json", ".example", ".gitignore", ".gitattributes")
PATH_SCAN_LIMIT = 1_000_000


def machine_path_hits(root, patterns=(ABSOLUTE_PATH,), allowed=ABSOLUTE_PATH_ALLOWED):
    """Return "relative/path: match" for every shipped text file with an absolute path."""
    paths = []
    for tree in PATH_SCAN_TREES:
        paths.extend(sorted((root / tree).rglob("*")))
    paths.extend(root / name for name in PATH_SCAN_FILES)

    found = []
    for path in paths:
        if not path.is_file() or path.name in PATH_SCAN_SKIP_NAMES:
            continue
        if path.suffix.lower() not in PATH_SCAN_SUFFIXES:
            continue
        if "__pycache__" in path.parts or path.stat().st_size > PATH_SCAN_LIMIT:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            for match in pattern.findall(text):
                if str(match) in allowed or len(str(match)) < PATH_SCAN_MIN_CHARS:
                    continue
                found.append(f"{path.relative_to(root).as_posix()}: {match}")
    return found


class FollowerTests(unittest.TestCase):
    def test_page_loads_stems_from_the_server(self):
        page = VIEWER.read_text(encoding="utf-8")
        self.assertIn("location.protocol === 'http:'", page)
        self.assertIn("/api/write", page)
        self.assertIn("/api/tracks", page)
        self.assertIn("/api/render", page)
        self.assertIn("vstAdd", page)
        self.assertIn("playBtn", page)
        self.assertIn('id="delDlg"', page)
        self.assertIn('id="rmBtn"', page)
        self.assertNotIn("Upload a song to Claude", page)
        self.assertNotIn("Delete forever", page)
        self.assertNotIn("Removed tracks", page)
        self.assertNotIn("Auto-sync", page)
        self.assertNotIn('id="autoSync"', page)
        self.assertIn('id="sM1" hidden', page)
        self.assertIn('id="curDot" hidden', page)
        self.assertIn("vstRemove", page)
        # The CC BY credit is a page footer, not part of the lanes that collapse.
        self.assertIn('<footer class="credit">', page)
        self.assertNotIn("</a> by Alexander Holm", page[:page.index('<footer class="credit">')])

        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp) / "demo-song"
            song.mkdir()
            wav(song / "stems" / "bass.wav")
            wav(song / "input.wav")
            (song / "voicings.json").write_text(json.dumps({
                "voicings": [{"t": 0, "chord": "C", "v": [48, 60, 64, 67]}],
            }), encoding="utf-8")
            (song / "track.json").write_text(json.dumps({
                "title": "Demo", "artist": "A", "key": "C major", "bpm": 120,
                "beatsPerBar": 4, "barStart": 0, "duration": 4,
                "sections": [{"name": "Intro", "start": 0, "end": 4}],
                "chords": [{
                    "t": 0, "chord": "C", "roman": "I", "conf": "low",
                    "options": [{"chord": "C", "roman": "I"}, {"chord": "Cmaj7", "roman": "Imaj7"}],
                }, {"t": 2, "chord": None, "roman": None, "conf": "low"}],
            }), encoding="utf-8")

            data = cf_data(song)
            track = data["tracks/demo-song"]
            self.assertEqual(track["chords"][0]["options"][1]["chord"], "Cmaj7")
            self.assertEqual(track["chords"][1]["chord"], "?")
            self.assertEqual(len(track["stems"]), 1)
            self.assertEqual(track["stems"][0]["kind"], "bass")
            self.assertIn("tracks/demo-song/parts/piano", data)

            httpd = make_server(song, 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
                self.assertIn("playBtn", html)
                self.assertNotIn("/api/chat", html)
                script = urllib.request.urlopen(f"http://127.0.0.1:{port}/data.js").read().decode("utf-8")
                self.assertIn("Demo", script)
                stem_id = track["stems"][0]["id"]
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/_blob/{stem_id}").read()
                self.assertTrue(body.startswith(b"RIFF"))
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/write",
                    data=json.dumps({"path": "picks/demo-song", "data": {"picks": {"0": 1}, "updated": "t"}}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as res:
                    self.assertEqual(res.status, 204)
                saved = json.loads((song / "picks.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["picks"]["0"], 1)
                again = urllib.request.urlopen(f"http://127.0.0.1:{port}/data.js").read().decode("utf-8")
                self.assertIn("picks/demo-song", again)
                denied = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/write",
                    data=json.dumps({"path": "../track.json", "data": {"x": 1}}).encode("utf-8"),
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(denied)
            finally:
                httpd.shutdown()
                httpd.server_close()


def post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def delete(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def minimal_song(folder, title, chord):
    folder.mkdir(parents=True)
    wav(folder / "stems" / "bass.wav")
    (folder / "track.json").write_text(json.dumps({
        "title": title, "artist": "A", "key": "C major", "bpm": 120,
        "chords": [{"t": 0, "chord": chord, "roman": "I", "conf": "low"}],
    }), encoding="utf-8")


class LibraryTests(unittest.TestCase):
    def test_library_lists_and_deletes_one_song_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            root.mkdir()
            (root / "README.md").write_text("keep\n", encoding="utf-8")
            (root / "notes").mkdir()
            minimal_song(root / "alpha", "Alpha", "C")
            minimal_song(root / "beta", "Beta", "G")
            outside = Path(tmp) / "outside"
            minimal_song(outside, "Outside", "F")

            data = cf_data(root)
            self.assertEqual(set(data) & {"tracks/alpha", "tracks/beta"}, {"tracks/alpha", "tracks/beta"})
            self.assertNotIn("tracks/outside", data)
            self.assertNotIn("tracks/notes", data)
            alpha_id = data["tracks/alpha"]["stems"][0]["id"]
            beta_id = data["tracks/beta"]["stems"][0]["id"]
            self.assertNotEqual(alpha_id, beta_id)

            httpd = make_server(root, 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                self.assertTrue(urllib.request.urlopen(f"http://127.0.0.1:{port}/_blob/{alpha_id}").read().startswith(b"RIFF"))
                self.assertTrue(urllib.request.urlopen(f"http://127.0.0.1:{port}/_blob/{beta_id}").read().startswith(b"RIFF"))
                # Remove is the only song control: the old hide flag is gone.
                status, _ = post(port, "/api/tracks", {"id": "alpha", "removed": True})
                self.assertEqual(status, 404)
                self.assertFalse((root / "alpha" / "library.json").exists())
                status, _ = post(port, "/api/write", {"path": "picks/beta", "data": {"picks": {"0": 1}}})
                self.assertEqual(status, 204)
                self.assertEqual(json.loads((root / "beta" / "picks.json").read_text(encoding="utf-8"))["picks"]["0"], 1)
                self.assertFalse((root / "alpha" / "picks.json").exists())
                status, _ = delete(port, "/api/tracks?id=beta")
                self.assertEqual(status, 204)
                self.assertFalse((root / "beta").exists())
                self.assertTrue((root / "alpha" / "track.json").is_file())
                self.assertTrue((root / "README.md").is_file())
                self.assertTrue(outside.is_dir())
                status, _ = delete(port, "/api/tracks?id=..")
                self.assertEqual(status, 404)
                status, _ = delete(port, "/api/tracks?id=outside")
                self.assertEqual(status, 404)
                minimal_song(root / "gamma", "Gamma", "Am")
                script = urllib.request.urlopen(f"http://127.0.0.1:{port}/data.js").read().decode("utf-8")
                self.assertIn("Gamma", script)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_libraries_txt_adds_every_song_and_delete_stays_one_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            extra = Path(tmp) / "extra"
            root.mkdir()
            minimal_song(root / "alpha", "Alpha", "C")
            minimal_song(extra / "beta", "Beta", "G")
            minimal_song(extra / "alpha", "Alpha Elsewhere", "Am")
            minimal_song(Path(tmp) / "lonely", "Lonely", "F")
            (root / "libraries.txt").write_text("# note\n\nnope\n../extra\n", encoding="utf-8")
            minimal_song(root / "one", "Only This", "C")
            (root / "one" / "libraries.txt").write_text(str(extra), encoding="utf-8")

            data = cf_data(root)
            self.assertIn("tracks/beta", data)
            # Two songs share the slug "alpha". Neither owns the bare id and
            # each gets a suffix from its own path, so a page that has not
            # reloaded cannot delete the other one by that id.
            self.assertNotIn("tracks/alpha", data)
            alphas = {key: data[key]["title"] for key in data if key.startswith("tracks/alpha-")}
            self.assertEqual(sorted(alphas.values()), ["Alpha", "Alpha Elsewhere"])
            other = [key for key, title in alphas.items() if title == "Alpha Elsewhere"]
            self.assertNotIn("tracks/lonely", data)
            self.assertNotIn("tracks/extra", data)
            one = cf_data(root / "one")
            self.assertEqual(set(key for key in one if key.startswith("tracks/")), {"tracks/one"})

            httpd = make_server(root, 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                beta_id = data["tracks/beta"]["stems"][0]["id"]
                self.assertTrue(urllib.request.urlopen(f"http://127.0.0.1:{port}/_blob/{beta_id}").read().startswith(b"RIFF"))
                status, _ = delete(port, "/api/tracks?id=beta")
                self.assertEqual(status, 204)
                self.assertFalse((extra / "beta").exists())
                self.assertTrue(extra.is_dir())
                self.assertTrue((extra / "alpha" / "track.json").is_file())
                self.assertTrue((root / "alpha" / "track.json").is_file())
                self.assertTrue((root / "libraries.txt").is_file())
                self.assertTrue((Path(tmp) / "lonely").is_dir())
                status, _ = delete(port, "/api/tracks?id=extra")
                self.assertEqual(status, 404)
                other_id = other[0].split("/", 1)[1]
                status, _ = delete(port, "/api/tracks?id=" + other_id)
                self.assertEqual(status, 204)
                self.assertFalse((extra / "alpha").exists())
                self.assertTrue((root / "alpha").is_dir())
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_song_ids_do_not_move_when_a_same_named_song_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            root.mkdir()
            minimal_song(root / "my_song", "Mine", "C")
            self.assertEqual({"my-song": root / "my_song"}, follower.song_index(root))
            minimal_song(root / "My Song", "Theirs", "G")
            later = follower.song_index(root)
            self.assertNotIn("my-song", later)
            self.assertIsNone(follower.find_song(root, "my-song"))
            self.assertEqual({"Mine", "Theirs"}, {cf_data(root)["tracks/" + key]["title"] for key in later})

    def test_a_broken_track_is_named_in_the_terminal(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            root.mkdir()
            minimal_song(root / "alpha", "Alpha", "C")
            broken = root / "broken"
            broken.mkdir()
            (broken / "track.json").write_text("{not json", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                data = cf_data(root)
            self.assertIn("tracks/alpha", data)
            self.assertNotIn("tracks/broken", data)
            self.assertIn("skipped", out.getvalue())
            self.assertIn("broken", out.getvalue())

    def test_a_track_without_duration_still_gets_an_end_time(self):
        # The page divides by duration for the scrub bar and stops at it, so a
        # track that forgot the key must not reach the page as 0.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            root.mkdir()
            minimal_song(root / "alpha", "Alpha", "C")
            self.assertEqual(cf_data(root)["tracks/alpha"]["duration"], 2.0)
            track = json.loads((root / "alpha" / "track.json").read_text(encoding="utf-8"))
            track["sections"] = [{"name": "Intro", "start": 0, "end": 7.5}]
            (root / "alpha" / "track.json").write_text(json.dumps(track), encoding="utf-8")
            self.assertEqual(cf_data(root)["tracks/alpha"]["duration"], 7.5)

    def test_launcher_has_no_machine_path(self):
        text = (Path(__file__).resolve().parents[1] / "start-follower.bat").read_text(encoding="utf-8")
        self.assertIn("python -m mdchord serve", text)
        self.assertIn("http://127.0.0.1:8765/", text)
        self.assertNotIn("MusicDigestSongs", text)
        self.assertNotIn("E:\\", text)

    def test_no_shipped_file_has_a_machine_path(self):
        root = Path(__file__).resolve().parents[1]
        # A stale entry here would silently stop scanning a real file, so the
        # list has to name files that exist.
        for name in PATH_SCAN_FILES:
            self.assertTrue((root / name).is_file(), f"PATH_SCAN_FILES names a missing file: {name}")
        self.assertEqual([], machine_path_hits(root))

    def test_the_path_scan_fires_on_a_planted_path(self):
        root = Path(__file__).resolve().parents[1]
        # Built at run time so this file stays clean enough for the scan above
        # to include it. The report holds the drive plus the first segment.
        planted = chr(69) + ":\\MDFX03\\Desktop"
        probe = root / "mdchord" / "_probe_path.py"
        probe.write_text(f"# built on {planted}\n", encoding="utf-8")
        try:
            hits = machine_path_hits(root)
        finally:
            probe.unlink()
        self.assertEqual([f"mdchord/_probe_path.py: {chr(69)}:\\MDFX03"], hits)

    def test_gitignore_keeps_local_state_out_of_the_repo(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".gitignore").read_text(encoding="utf-8")
        rules = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        for pattern in ("__pycache__/", ".env", "instruments.json", "backup/", "*.m4a"):
            self.assertIn(pattern, rules)
        # The bundled sample bank has to survive the *.m4a rule above it.
        self.assertIn("!instruments/salamander.m4a", rules)
        self.assertEqual("!songs/README.md", rules[rules.index("songs/*") + 1])
        # Aurora Grand links JUCE and must not be redistributed from here. Only
        # the two Salamander files ship out of instruments/.
        self.assertEqual("!instruments/salamander.json", rules[rules.index("instruments/*") + 1])
        self.assertEqual("!instruments/salamander.m4a", rules[rules.index("instruments/*") + 2])

    def test_an_empty_library_still_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "songs"
            root.mkdir()
            httpd = make_server(root, 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
                self.assertIn("playBtn", html)
                script = urllib.request.urlopen(f"http://127.0.0.1:{port}/data.js").read().decode("utf-8")
                self.assertNotIn("tracks/", script)
            finally:
                httpd.shutdown()
                httpd.server_close()


class DemoTests(unittest.TestCase):
    def test_demo_writes_an_original_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_demo(Path(tmp) / "demo")
            for name in ("stems/drums.wav", "stems/bass.wav", "input.wav"):
                body = (out / name).read_bytes()
                self.assertTrue(body.startswith(b"RIFF"), name)
            track = json.loads((out / "track.json").read_text(encoding="utf-8"))
            self.assertEqual([c["chord"] for c in track["chords"]], ["C", "G", "Am", "F"])
            self.assertIn("Original 8 second loop", " ".join(track["notes"]))
            # The demo must satisfy the naming spec it ships, or the first
            # command a new user tries would fail.
            self.assertTrue((out / "measurement.json").is_file())
            _, errors = validate(track, json.loads((out / "measurement.json").read_text(encoding="utf-8")))
            self.assertEqual([], errors)


class InstrumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_catalog = vst.CATALOG
        self.old_bundled = vst.BUNDLED
        self.old_sample_doc = vst.SAMPLE_DOC
        self.old_sample_audio = vst.SAMPLE_AUDIO
        vst.CATALOG = Path(self.tmp.name) / "instruments.json"
        vst.BUNDLED = Path(self.tmp.name) / "missing-aurora.vst3"
        vst.SAMPLE_DOC = Path(self.tmp.name) / "missing-salamander.json"
        vst.SAMPLE_AUDIO = Path(self.tmp.name) / "missing-salamander.m4a"
        vst._loaded.clear()
        song = Path(self.tmp.name) / "demo-song"
        song.mkdir()
        (song / "track.json").write_text(json.dumps({
            "title": "Demo", "chords": [{"t": 0, "chord": "C", "roman": "I"}],
        }), encoding="utf-8")
        self.httpd = make_server(song, 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        vst.CATALOG = self.old_catalog
        vst.BUNDLED = self.old_bundled
        vst.SAMPLE_DOC = self.old_sample_doc
        vst.SAMPLE_AUDIO = self.old_sample_audio
        vst._loaded.clear()
        self.tmp.cleanup()

    def test_bad_paths_and_unknown_renders_are_rejected(self):
        status, body = post(self.port, "/api/instruments", {"path": ""})
        self.assertEqual(status, 400)
        self.assertIn(b".vst3", body)
        status, body = post(self.port, "/api/instruments", {"path": r"C:\nope.txt"})
        self.assertEqual(status, 400)
        self.assertIn(b".vst3", body)
        status, body = post(self.port, "/api/instruments", {"path": r"C:\missing\NoSuch.vst3"})
        self.assertEqual(status, 400)
        self.assertIn(b"does not exist", body)
        listed = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        self.assertEqual(listed, [])
        status, body = post(self.port, "/api/render", {"id": "missing", "notes": [60], "seconds": 1})
        self.assertEqual(status, 400)
        self.assertIn(b"Unknown", body)

    def test_plugin_calls_stay_on_one_thread(self):
        seen = []

        def probe():
            seen.append(threading.current_thread().name)
            return 7

        self.assertEqual(vst._call(probe), 7)
        vst._call(probe)
        self.assertEqual(seen, ["vst-main", "vst-main"])

        def boom():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            vst._call(boom)

    def test_salamander_is_the_other_style(self):
        doc = {"asset": "abc123", "name": "Salamander Grand Piano", "samples": [{"midi": 60, "start": 0, "dur": 1, "name": "C4"}]}
        audio = Path(self.tmp.name) / "sal.m4a"
        meta = Path(self.tmp.name) / "sal.json"
        audio.write_bytes(b"ftyp-test")
        meta.write_text(json.dumps(doc), encoding="utf-8")
        vst.SAMPLE_DOC = meta
        vst.SAMPLE_AUDIO = audio
        listed = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        row = next(item for item in listed if item["id"] == "salamander")
        self.assertEqual(row["kind"], "samples")
        # The sampled bank is the default now that no plugin is bundled.
        self.assertTrue(row["default"])
        body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/_blob/abc123").read()
        self.assertEqual(body, b"ftyp-test")
        page = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/data.js").read().decode("utf-8")
        self.assertIn("instruments/piano", page)
        self.assertIn("abc123", page)

    def test_bundled_piano_is_the_default(self):
        bundle = Path(self.tmp.name) / "Aurora Grand.vst3"
        binary = bundle / "Contents" / "x86_64-win" / "Aurora Grand.vst3"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"")
        vst.BUNDLED = bundle
        listed = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        self.assertEqual(listed[0]["name"], "Aurora Grand")
        self.assertTrue(listed[0]["default"])
        vst._write([{"id": "kept", "name": "Aurora Grand", "path": str(bundle.resolve())}])
        again = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["id"], "kept")
        self.assertTrue(again[0]["default"])

    def test_a_vst3_directory_is_a_valid_path(self):
        bundle = Path(self.tmp.name) / "Piano.vst3"
        binary = bundle / "Contents" / "x86_64-win" / "Piano.vst3"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"not a plugin")
        self.assertEqual(vst._plugin_file(f'"{bundle}"'), bundle.resolve())
        self.assertEqual(vst._load_paths(bundle.resolve()), [bundle.resolve(), binary.resolve()])

    def test_add_and_remove_round_trip_without_loading_a_plugin(self):
        def fake_add(text):
            item = {"id": "added1", "name": "Room", "path": text}
            vst._write([item])
            return item

        old = follower.add_instrument
        follower.add_instrument = fake_add
        try:
            status, body = post(self.port, "/api/instruments", {"path": r"C:\VST3\Room.vst3"})
        finally:
            follower.add_instrument = old
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["name"], "Room")
        listed = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        self.assertEqual(listed[0]["id"], "added1")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/instruments?id=added1",
            method="DELETE",
        )
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 204)
        listed = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/instruments").read())
        self.assertEqual(listed, [])


class ShippedInstrumentTests(unittest.TestCase):
    """Reads what the repository actually ships, not a temp substitute."""

    def test_the_sampled_bank_ships_and_is_the_default(self):
        # This pack carries no VST3, so the sampled bank is what the page must
        # pick. Without a default entry the instrument selector falls back to
        # "Off" and chord playback is silent.
        saved = (vst.CATALOG, vst.BUNDLED, vst.SAMPLE_DOC, vst.SAMPLE_AUDIO)
        with tempfile.TemporaryDirectory() as tmp:
            vst.CATALOG = Path(tmp) / "instruments.json"
            vst.BUNDLED = Path(tmp) / "no-bundled-piano.vst3"
            try:
                row = vst._sample_record()
                self.assertIsNotNone(row, "the shipped sample bank is missing")
                self.assertEqual("salamander", row["id"])
                self.assertEqual("samples", row["kind"])
                self.assertTrue(row["default"])
                listed = vst.list_instruments()
            finally:
                vst.CATALOG, vst.BUNDLED, vst.SAMPLE_DOC, vst.SAMPLE_AUDIO = saved
        self.assertEqual(1, len(listed))
        self.assertEqual("salamander", listed[0]["id"])
        self.assertTrue(listed[0]["default"])


class ByteOrderMarkTests(unittest.TestCase):
    def test_a_track_saved_with_a_bom_is_still_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp) / "lib" / "notepad"
            build_demo(song)
            text = (song / "track.json").read_text(encoding="utf-8")
            (song / "track.json").write_text(text, encoding="utf-8-sig")
            (song / "picks.json").write_text('{"picks": {}}', encoding="utf-8-sig")
            data = cf_data(song.parent)
        self.assertIn("tracks/notepad", data)
        self.assertIn("picks/notepad", data)


class CrossSiteTests(unittest.TestCase):
    """Another tab in the same browser must not reach the local server."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.song = Path(self.tmp.name) / "demo"
        build_demo(self.song)
        self.httpd = make_server(self.song, 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def send(self, path, method="GET", body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body,
                                     headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_page_requests_still_work(self):
        same = {"Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "application/json"}
        body = json.dumps({"path": "picks/demo", "data": {"picks": {}}}).encode("utf-8")
        self.assertEqual(204, self.send("/api/write", "POST", body, same))
        self.assertEqual(200, self.send("/data.js", headers={"Host": f"localhost:{self.port}"}))

    def test_foreign_origin_is_refused(self):
        body = json.dumps({"path": "picks/demo", "data": {"x": 1}}).encode("utf-8")
        headers = {"Origin": "https://evil.example", "Content-Type": "application/json"}
        self.assertEqual(403, self.send("/api/write", "POST", body, headers))
        self.assertEqual(403, self.send("/api/tracks?id=demo", "DELETE", headers={"Origin": "https://evil.example"}))
        self.assertFalse((self.song / "picks.json").exists())
        self.assertTrue((self.song / "track.json").is_file())

    def test_simple_cross_site_post_is_refused(self):
        body = json.dumps({"path": "picks/demo", "data": {"x": 1}}).encode("utf-8")
        self.assertEqual(415, self.send("/api/write", "POST", body, {"Content-Type": "text/plain"}))
        self.assertFalse((self.song / "picks.json").exists())

    def test_a_cross_site_script_tag_cannot_read_the_library(self):
        # <script src="http://127.0.0.1:PORT/data.js"> on another site sends
        # the right Host and no Origin; only the browser's own label tells.
        tag = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"}
        self.assertEqual(403, self.send("/data.js", headers=tag))
        self.assertEqual(403, self.send("/data.js", headers=dict(tag, **{"Sec-Fetch-Site": "same-site"})))
        self.assertEqual(403, self.send("/api/instruments", headers=tag))
        self.assertEqual(403, self.send("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"}))
        # The page's own script tag, a typed address, and a link from elsewhere still work.
        self.assertEqual(200, self.send("/data.js", headers=dict(tag, **{"Sec-Fetch-Site": "same-origin"})))
        self.assertEqual(200, self.send("/data.js", headers=dict(tag, **{"Sec-Fetch-Site": "none"})))
        self.assertEqual(200, self.send("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}))

    def test_rebound_host_is_refused(self):
        self.assertEqual(403, self.send("/data.js", headers={"Host": f"attacker.example:{self.port}"}))


class ServerRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "songs"
        self.root.mkdir()
        minimal_song(self.root / "alpha", "Alpha", "C")
        self.httpd = make_server(self.root, 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_a_bad_content_length_is_a_400_not_a_traceback(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/write", body=None,
                     headers={"Content-Type": "application/json", "Content-Length": "abc"})
        res = conn.getresponse()
        self.assertEqual(res.status, 400)
        self.assertEqual(res.read(), b"bad body")
        conn.close()

    def test_a_locked_folder_reports_409_and_stays_listed(self):
        def locked(path, *args, **kwargs):
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")

        old = follower.shutil.rmtree
        follower.shutil.rmtree = locked
        try:
            status, body = delete(self.port, "/api/tracks?id=alpha")
        finally:
            follower.shutil.rmtree = old
        self.assertEqual(status, 409)
        self.assertIn(b"could not delete", body)
        self.assertTrue((self.root / "alpha" / "track.json").is_file())
        self.assertIn("tracks/alpha", cf_data(self.root))


class ViewerScriptTests(unittest.TestCase):
    def test_inline_scripts_parse(self):
        html = VIEWER.read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertGreaterEqual(len(scripts), 3)
        with tempfile.TemporaryDirectory() as tmp:
            for index, source in enumerate(scripts):
                path = Path(tmp) / f"part{index}.js"
                path.write_text(source, encoding="utf-8")
                subprocess.run(["node", "--check", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()
