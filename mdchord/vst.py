"""Load VST3 instruments the user already has and render chord notes.

The plugin file stays where it is. This catalog stores the path only.
"""

import hashlib
import io
import json
import queue
import threading
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "instruments.json"
BUNDLED = ROOT / "instruments" / "Aurora Grand.vst3"
SAMPLE_DOC = ROOT / "instruments" / "salamander.json"
SAMPLE_AUDIO = ROOT / "instruments" / "salamander.m4a"
_lock = threading.Lock()
_loaded = {}
_jobs = queue.Queue()
_worker = None
_worker_guard = threading.Lock()


def _read():
    if not CATALOG.is_file():
        return []
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write(items):
    CATALOG.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _same_path(left, right):
    try:
        return Path(left).resolve().as_posix().lower() == Path(right).resolve().as_posix().lower()
    except OSError:
        return False


def _bundled_record():
    if not BUNDLED.exists():
        return None
    loaded = BUNDLED
    folder = BUNDLED / "Contents" / "x86_64-win"
    if folder.is_dir():
        binaries = [item for item in sorted(folder.glob("*.vst3")) if item.is_file()]
        if binaries:
            loaded = binaries[0]
    ident = hashlib.md5(str(BUNDLED.resolve()).lower().encode("utf-8")).hexdigest()[:12]
    return {
        "id": ident,
        "name": "Aurora Grand",
        "path": str(BUNDLED.resolve()),
        "load": str(loaded.resolve()),
        "default": True,
    }


def sample_audio():
    return SAMPLE_AUDIO if SAMPLE_AUDIO.is_file() else None


def sample_doc():
    if not SAMPLE_DOC.is_file() or not SAMPLE_AUDIO.is_file():
        return None
    try:
        data = json.loads(SAMPLE_DOC.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("asset") or not isinstance(data.get("samples"), list):
        return None
    return data


def _sample_record():
    doc = sample_doc()
    if not doc:
        return None
    return {
        "id": "salamander",
        "name": doc.get("name") or "Salamander Grand Piano",
        "kind": "samples",
        "path": str(SAMPLE_AUDIO.resolve()),
        # The sampled bank is what ships, so the page picks it when no bundled
        # VST3 is present. A bundled VST3 still wins: list_instruments() puts it
        # at index 0 and the page takes the first entry marked default.
        "default": True,
    }


def _find(ident):
    for item in _read():
        if item.get("id") == ident:
            return item
    bundled = _bundled_record()
    if bundled and bundled["id"] == ident:
        return bundled
    return None


def list_instruments():
    rows = []
    for item in _read():
        if item.get("id") and item.get("path"):
            rows.append({"id": item["id"], "name": item.get("name"), "path": item["path"], "kind": "vst"})
    bundled = _bundled_record()
    if bundled:
        matched = False
        for row in rows:
            if _same_path(row["path"], bundled["path"]):
                row["default"] = True
                row["kind"] = "vst"
                matched = True
        if not matched:
            rows.insert(0, {
                "id": bundled["id"], "name": bundled["name"], "path": bundled["path"],
                "kind": "vst", "default": True,
            })
    sample = _sample_record()
    if sample and not any(row["id"] == sample["id"] for row in rows):
        at = 1 if rows and rows[0].get("default") else 0
        rows.insert(at, sample)
    return rows


def _plugin_file(text):
    raw = str(text or "").strip().strip('"')
    if not raw:
        raise ValueError("Enter the full path to a .vst3 instrument.")
    path = Path(raw)
    if path.suffix.lower() != ".vst3":
        raise ValueError("The path has to end in .vst3. Effects and other plugin formats are not used.")
    if not path.exists():
        raise ValueError("That path does not exist.")
    return path.resolve()


def _load_paths(path):
    """Bundle first, then the Windows plugin file inside it.

    Pedalboard can open some .vst3 folders and not others. The file that
    actually loads is Contents/x86_64-win/<name>.vst3.
    """
    if path.is_file():
        return [path]
    paths = [path]
    folder = path / "Contents" / "x86_64-win"
    if folder.is_dir():
        paths.extend(item for item in sorted(folder.glob("*.vst3")) if item.is_file())
    return paths


def _instantiate(path):
    try:
        from pedalboard import load_plugin
    except ImportError as exc:
        raise RuntimeError("Install pedalboard before adding a VST3: pip install pedalboard") from exc
    last = None
    for candidate in _load_paths(path):
        try:
            return load_plugin(str(candidate)), candidate
        except Exception as exc:
            last = exc
    raise ValueError(f"Could not load this VST3: {last}") from last


def _require_instrument(plugin):
    if getattr(plugin, "is_instrument", None) is False:
        raise ValueError("This VST3 is an effect, not an instrument.")
    return plugin


def _worker_main():
    while True:
        job = _jobs.get()
        if job is None:
            return
        fn, args, box = job
        try:
            box["value"] = fn(*args)
        except Exception as exc:
            box["error"] = exc
        finally:
            box["ready"].set()


def _ensure_worker():
    global _worker
    with _worker_guard:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_main, name="vst-main", daemon=True)
            _worker.start()
    return _worker


def _call(fn, *args):
    """Run plugin work on one thread.

    JUCE treats the first thread that loads a plugin as its main thread.
    HTTP requests arrive on other threads, and reloading there raises.
    """
    worker = _ensure_worker()
    if threading.current_thread() is worker:
        return fn(*args)
    box = {"ready": threading.Event()}
    _jobs.put((fn, args, box))
    box["ready"].wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _add_instrument(text):
    path = _plugin_file(text)
    plugin, loaded = _instantiate(path)
    _require_instrument(plugin)
    ident = hashlib.md5(str(path).lower().encode("utf-8")).hexdigest()[:12]
    item = {"id": ident, "name": path.stem, "path": str(path), "load": str(loaded)}
    items = [row for row in _read() if row.get("id") != ident]
    items.append(item)
    _write(items)
    with _lock:
        _loaded[ident] = plugin
    return item


def add_instrument(text):
    return _call(_add_instrument, text)


def _remove_instrument(ident):
    _write([row for row in _read() if row.get("id") != ident])
    with _lock:
        _loaded.pop(ident, None)


def remove_instrument(ident):
    _call(_remove_instrument, ident)


def _wav_bytes(audio, sample_rate):
    import numpy as np
    data = np.asarray(audio, dtype="float32")
    if data.size == 0:
        raise RuntimeError("The instrument returned silence.")
    if data.ndim == 1:
        data = data[None, :]
    channels, count = data.shape
    if channels > 2:
        data = data[:2]
        channels = 2
    pcm = np.clip(data, -1, 1).T.reshape(count, channels)
    interleaved = (pcm * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(interleaved)
    return buf.getvalue()


def _render_wav(ident, notes, seconds):
    item = _find(ident)
    if not item:
        raise ValueError("Unknown instrument. Add it again.")
    try:
        midi = [int(note) for note in notes]
    except (TypeError, ValueError) as exc:
        raise ValueError("Notes must be MIDI numbers.") from exc
    if not 1 <= len(midi) <= 8 or any(note < 0 or note > 127 for note in midi):
        raise ValueError("Send 1 to 8 MIDI notes.")
    try:
        length = float(seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration is not a number.") from exc
    if not 0.2 <= length <= 8:
        raise ValueError("Duration must be from 0.2 to 8 seconds.")
    user_path = Path(item["path"])
    load_path = Path(item["load"]) if item.get("load") else user_path
    if not load_path.exists() and not user_path.exists():
        raise ValueError("The VST3 file is no longer at the saved path.")
    try:
        from mido import Message
    except ImportError as exc:
        raise RuntimeError("Install pedalboard before rendering: pip install pedalboard") from exc
    with _lock:
        plugin = _loaded.get(ident)
        if plugin is None:
            plugin, _loaded_path = _instantiate(load_path if load_path.exists() else user_path)
            _require_instrument(plugin)
            _loaded[ident] = plugin
        if hasattr(plugin, "reset"):
            plugin.reset()
        messages = [Message("note_on", note=note, velocity=96, time=0) for note in midi]
        messages += [Message("note_off", note=note, velocity=0, time=max(0.05, length - 0.08)) for note in midi]
        try:
            audio = plugin(messages, duration=length, sample_rate=44100, num_channels=2, reset=False)
        except Exception as exc:
            raise RuntimeError(f"The instrument did not render: {exc}") from exc
    return _wav_bytes(audio, 44100)


def render_wav(ident, notes, seconds):
    return _call(_render_wav, ident, notes, seconds)
