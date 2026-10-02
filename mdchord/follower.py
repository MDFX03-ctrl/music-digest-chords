"""Serve Chord Follower for a song library, or for one song folder.

`songs/` is a library: each direct child with track.json is one song.
`songs/libraries.txt` may name more library folders, one path per line.
A folder that itself contains track.json is still one song.
Stems are the wav files in stems/. The page asks for /_blob/<id>; this server
streams the matching wav. Picks and row layouts are written back into that
song's folder. Remove deletes only that song folder.
"""

import hashlib
import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mdchord.pipeline import DigestError
from mdchord.vst import add_instrument, list_instruments, remove_instrument, render_wav, sample_audio, sample_doc

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer" / "index.html"
ORDER = ["vocals", "drums", "bass", "guitar", "piano", "other"]
LABELS = {
    "vocals": "Vocals", "drums": "Drums", "bass": "Bass",
    "guitar": "Guitar", "piano": "Piano", "other": "Other",
}


def blob_id(track, rel):
    return hashlib.md5(f"{track}\n{rel}".encode("utf-8")).hexdigest()


def track_id(song):
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in Path(song).name).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "song"


def song_dirs(root):
    """One song folder, or each direct child of a library that has track.json."""
    root = Path(root)
    if (root / "track.json").is_file():
        return [root]
    if not root.is_dir():
        return []
    found = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(".") or child.is_symlink():
            continue
        if child.is_dir() and (child / "track.json").is_file():
            found.append(child)
    return found


def library_roots(root):
    """The served folder, plus library folders named in songs/libraries.txt.

    A folder that itself has track.json is one song. Its libraries.txt is ignored.
    Missing paths are skipped. A line may be absolute, or relative to the served folder.
    """
    root = Path(root)
    if (root / "track.json").is_file():
        return [root]
    roots = [root]
    seen = set()
    if root.exists():
        seen.add(root.resolve())
    listing = root / "libraries.txt"
    if not listing.is_file():
        return roots
    try:
        lines = listing.read_text(encoding="utf-8").splitlines()
    except OSError:
        return roots
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line)
        if not path.is_absolute():
            path = root / path
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_dir():
            continue
        seen.add(path)
        roots.append(path)
    return roots


def iter_songs(root):
    seen = set()
    for library in library_roots(root):
        for song in song_dirs(library):
            if song.is_symlink():
                continue
            try:
                key = song.resolve()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            yield song


def song_index(root):
    used = {}
    for song in iter_songs(root):
        ident = track_id(song)
        if ident in used:
            digest = hashlib.md5(str(song.resolve()).encode("utf-8")).hexdigest()
            ident = track_id(song) + "-" + digest[:6]
            if ident in used:
                ident = track_id(song) + "-" + digest
        used[ident] = song
    return used


def find_song(root, ident):
    if not isinstance(ident, str) or not ident or any(ch in ident for ch in "/\\") or ".." in ident:
        return None
    return song_index(root).get(ident)


def assets(song, ident):
    found = {}
    stems = song / "stems"
    if stems.is_dir():
        for name in ORDER:
            path = stems / (name + ".wav")
            if path.is_file() and not path.is_symlink():
                found[blob_id(ident, "stems/" + name + ".wav")] = path
    mix = song / "input.wav"
    if mix.is_file() and not mix.is_symlink():
        found[blob_id(ident, "input.wav")] = mix
    return found


def all_assets(root):
    found = {}
    for ident, song in song_index(root).items():
        found.update(assets(song, ident))
    return found


def _load(path, default):
    if not path.is_file():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _page_chord(chord):
    name = chord.get("chord") or "?"
    roman = chord.get("roman") if chord.get("chord") else (chord.get("roman") or "?")
    out = {"t": chord.get("t"), "chord": name, "roman": roman}
    if chord.get("conf"):
        out["conf"] = chord["conf"]
    options = []
    for opt in chord.get("options") or []:
        if opt.get("chord"):
            options.append({"chord": opt["chord"], "roman": opt.get("roman") or "?"})
    if options:
        out["options"] = options
    return out


def _removed_mark(song):
    state = _load(song / "library.json", None)
    if not isinstance(state, dict):
        return None
    flag = state.get("removed")
    if flag is True or (isinstance(flag, str) and flag):
        return flag
    return None


def _one_track(song, ident):
    track = _load(song / "track.json", None)
    if not isinstance(track, dict) or not isinstance(track.get("chords"), list):
        raise DigestError([f"No chord track in {song / 'track.json'}"])
    files = assets(song, ident)
    stems = []
    for name in ORDER:
        ident_blob = blob_id(ident, "stems/" + name + ".wav")
        if ident_blob in files:
            stems.append({"id": ident_blob, "kind": name, "name": LABELS[name], "offset": 0})
    audios = []
    mix_id = blob_id(ident, "input.wav")
    if mix_id in files:
        audios.append({"id": mix_id, "label": "Full mix", "offset": 0})
    notes = track.get("notes") if isinstance(track.get("notes"), list) else []
    page = {
        "title": track.get("title") or song.name,
        "artist": track.get("artist") or "",
        "key": track.get("key") or "",
        "keys": track.get("keys") or ([{"t": track.get("barStart", track.get("bar_start") or 0), "key": track.get("key")}] if track.get("key") else []),
        "bpm": track.get("bpm"),
        "beatsPerBar": track.get("beatsPerBar", track.get("beats_per_bar") or 4),
        "barStart": track.get("barStart", track.get("bar_start") or 0),
        "duration": track.get("duration") or 0,
        "sections": track.get("sections") or [],
        "chords": [_page_chord(chord) for chord in track["chords"]],
        "stems": stems,
        "audios": audios,
        "note": " ".join(str(item) for item in notes),
        "created": track.get("created") or "",
        "verified": bool(track.get("verified")),
    }
    mark = _removed_mark(song)
    if mark:
        page["removed"] = mark
    data = {"tracks/" + ident: page}
    voicings = _load(song / "voicings.json", None)
    if isinstance(voicings, dict) and isinstance(voicings.get("voicings"), list):
        data["tracks/" + ident + "/parts/piano"] = voicings
    picks = _load(song / "picks.json", None)
    if isinstance(picks, dict):
        data["picks/" + ident] = picks
    layout = _load(song / "layout.json", None)
    if isinstance(layout, dict):
        data["layouts/" + ident] = layout
    return data


def cf_data(root):
    root = Path(root)
    data = {}
    for ident, song in song_index(root).items():
        try:
            data.update(_one_track(song, ident))
        except (DigestError, OSError, UnicodeError, json.JSONDecodeError):
            continue
    piano = sample_doc()
    if piano:
        data["instruments/piano"] = piano
    return data


def data_js(root):
    return "window.__CF_DATA=" + json.dumps(cf_data(root), ensure_ascii=False) + ";\n"


def _removed_value(value):
    if value is False or value is None or value == "":
        return None
    if value is True:
        return True
    if isinstance(value, str) and len(value) <= 40 and not any(ch in value for ch in "\r\n/\\"):
        return value
    raise ValueError("bad removed")


def set_removed(root, ident, value):
    song = find_song(root, ident)
    if song is None:
        return "missing"
    try:
        stored = _removed_value(value)
    except ValueError:
        return "bad"
    path = song / "library.json"
    if stored is None:
        if path.is_file():
            path.unlink()
        return "ok"
    path.write_text(json.dumps({"removed": stored}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "ok"


def delete_song(root, ident):
    """Delete one song folder. Never a library folder that only holds songs."""
    song = find_song(root, ident)
    if song is None or song.is_symlink():
        return False
    try:
        song = song.resolve()
    except OSError:
        return False
    if not (song / "track.json").is_file():
        return False
    for library in library_roots(root):
        try:
            library = library.resolve()
        except OSError:
            continue
        if (library / "track.json").is_file():
            if song == library:
                shutil.rmtree(song)
                return True
            continue
        if song.parent == library:
            shutil.rmtree(song)
            return True
    return False


def _save_doc(root, path, payload):
    if not isinstance(path, str) or not isinstance(payload, dict):
        return False
    kind, _, ident = path.partition("/")
    if kind not in ("picks", "layouts") or not ident or "/" in ident:
        return False
    song = find_song(root, ident)
    if song is None:
        return False
    dest = song / ("picks.json" if kind == "picks" else "layout.json")
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def build_handler(root):
    root = Path(root).resolve()
    viewer = VIEWER.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def _local(self):
            """Only this page may talk to the server.

            A Host other than 127.0.0.1 or localhost on this port is a DNS
            rebinding attempt. An Origin from anywhere else is another site in
            the same browser. Either one gets 403.
            """
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if (self.headers.get("Host") or "").lower() not in allowed:
                self._bytes(403, "text/plain; charset=utf-8", b"forbidden host")
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin.lower() not in {"http://" + item for item in allowed}:
                self._bytes(403, "text/plain; charset=utf-8", b"forbidden origin")
                return False
            return True

        def do_GET(self):
            if not self._local():
                return
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._bytes(200, "text/html; charset=utf-8", viewer)
                return
            if path == "/api/instruments":
                body = json.dumps(list_instruments()).encode("utf-8")
                self._bytes(200, "application/json; charset=utf-8", body)
                return
            if path == "/data.js":
                try:
                    body = data_js(root).encode("utf-8")
                except DigestError as exc:
                    self._bytes(404, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                    return
                self._bytes(200, "text/javascript; charset=utf-8", body)
                return
            blob = path[len("/_blob/"):] if path.startswith("/_blob/") else ""
            target = all_assets(root).get(blob)
            mime = "audio/wav" if target is not None and target.suffix.lower() == ".wav" else "application/octet-stream"
            piano = sample_doc()
            audio = sample_audio()
            if target is None and piano and audio is not None and blob == piano.get("asset"):
                target = audio
                mime = "audio/mp4"
            if target is None:
                self._bytes(404, "text/plain; charset=utf-8", b"not found")
                return
            self._file(200, mime, target)

        def do_POST(self):
            if not self._local():
                return
            # A cross-site form or text/plain fetch skips the CORS preflight.
            # application/json does not, so it is the only type accepted.
            kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if kind != "application/json":
                self._bytes(415, "text/plain; charset=utf-8", b"send application/json")
                return
            path = urlparse(self.path).path
            payload, error = self._payload()
            if error:
                self._bytes(400, "text/plain; charset=utf-8", error)
                return
            if path == "/api/instruments":
                try:
                    item = add_instrument(payload.get("path") or "")
                except ValueError as exc:
                    self._bytes(400, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                    return
                except RuntimeError as exc:
                    self._bytes(503, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                    return
                self._bytes(200, "application/json; charset=utf-8", json.dumps(item).encode("utf-8"))
                return
            if path == "/api/render":
                try:
                    body = render_wav(payload.get("id"), payload.get("notes") or [], payload.get("seconds") or 2)
                except ValueError as exc:
                    self._bytes(400, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                    return
                except RuntimeError as exc:
                    self._bytes(503, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                    return
                self._bytes(200, "audio/wav", body)
                return
            if path == "/api/tracks":
                if not isinstance(payload, dict) or "removed" not in payload:
                    self._bytes(400, "text/plain; charset=utf-8", b"bad removed")
                    return
                result = set_removed(root, payload.get("id"), payload.get("removed"))
                if result == "missing":
                    self._bytes(404, "text/plain; charset=utf-8", b"not found")
                    return
                if result == "bad":
                    self._bytes(400, "text/plain; charset=utf-8", b"bad removed")
                    return
                self._bytes(204, "text/plain", b"")
                return
            if path != "/api/write":
                self._bytes(404, "text/plain; charset=utf-8", b"not found")
                return
            if not _save_doc(root, payload.get("path"), payload.get("data")):
                self._bytes(403, "text/plain; charset=utf-8", b"path not saved")
                return
            self._bytes(204, "text/plain", b"")

        def do_DELETE(self):
            if not self._local():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/api/instruments":
                ident = parse_qs(parsed.query).get("id", [""])[0]
                remove_instrument(ident)
                self._bytes(204, "text/plain", b"")
                return
            if parsed.path == "/api/tracks":
                ident = parse_qs(parsed.query).get("id", [""])[0]
                if not delete_song(root, ident):
                    self._bytes(404, "text/plain; charset=utf-8", b"not found")
                    return
                self._bytes(204, "text/plain", b"")
                return
            self._bytes(404, "text/plain; charset=utf-8", b"not found")

        def _payload(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1_000_000:
                return None, b"bad body"
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return None, b"bad json"
            if not isinstance(payload, dict):
                return None, b"bad json"
            return payload, None

        def _bytes(self, status, mime, body):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _file(self, status, mime, path):
            size = path.stat().st_size
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def log_message(self, fmt, *args):
            print("%s %s" % (self.address_string(), fmt % args), flush=True)

    return Handler


def make_server(root, port=8765):
    root = Path(root)
    if not root.is_dir():
        raise DigestError([f"No song folder at {root}"])
    return ThreadingHTTPServer(("127.0.0.1", port), build_handler(root))


def serve(root, port=8765):
    root = Path(root)
    if not root.exists() and root == Path("songs"):
        root.mkdir()
    httpd = make_server(root, port)
    host, bound = httpd.server_address
    count = len(song_index(root))
    print(f"Chord Follower: http://{host}:{bound}/", flush=True)
    print(f"{count} song(s)", flush=True)
    for item in library_roots(root):
        print(f"  {item.resolve()}", flush=True)
    print("Stop with Ctrl+C.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        httpd.server_close()
