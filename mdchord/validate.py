"""Check a hand-written track.json against the measurement and chordtones.js."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHORDTONES = ROOT / "tools" / "chordtones.js"
PC = re.compile(r"^[A-G](#|b)?$")
TIME_TOL = 0.05
# Root, then in this order and each at most once: triad quality, a seventh or
# extension, sus, add9, alterations. m7b5 is m + 7 + b5, dim7 is dim + 7.
QUALITY = re.compile(
    r"^[A-G][#b]?(m|min|dim|aug)?(maj7|maj9|maj11|maj13|6|7|9|11|13)?(sus2|sus4)?(add9)?"
    r"(?P<alt>(b5|#5|b9|#9|#11|b13)*)$"
)


def allowed_times(bars):
    times = []
    for bar in bars.get("bars") or []:
        times.append(float(bar["t"]))
        for part in bar.get("parts") or []:
            times.append(float(part["t"]))
    return times


def snap(value, times):
    if value is None or not times:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    best = min(times, key=lambda item: abs(item - number))
    if abs(best - number) > TIME_TOL:
        return None
    return best


def parse_ok(symbols):
    needed = [s for s in symbols if s and s != "N.C."]
    if not needed:
        return {}
    script = (
        "const CT=require(" + json.dumps(str(CHORDTONES)) + ");"
        "const syms=" + json.dumps(needed) + ";"
        "const o={}; for (const s of syms) o[s]=CT.parse(s)!==null;"
        "console.log(JSON.stringify(o));"
    )
    out = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(out)


def _candidates_at(candidates, t):
    """Chord names scored for the part time nearest t, keyed as the tools save them."""
    try:
        number = float(t)
    except (TypeError, ValueError):
        return set()
    names = set()
    for key, rows in candidates.items():
        try:
            close = abs(float(key) - number) <= TIME_TOL
        except (TypeError, ValueError):
            continue
        if close and isinstance(rows, list):
            names.update(row["chord"] for row in rows if isinstance(row, dict) and isinstance(row.get("chord"), str))
    return names


def _usual_beats(bars):
    counts = {}
    for bar in bars.get("bars") or []:
        beats = int(bar.get("beats") or 4)
        counts[beats] = counts.get(beats, 0) + 1
    return max(counts, key=counts.get) if counts else 4


class ValidateError(RuntimeError):
    """Raised when a hand-written track.json does not follow the naming spec."""

    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = list(errors)


def check_symbol(symbol):
    """True when the symbol matches the grammar in prompts/chord-naming.md.

    tools/chordtones.js is deliberately forgiving: it strips "?" and whitespace
    and falls back to a major triad, so it cannot tell "G" from "G???" or
    "Gxyz". The spec allows neither, so the shape is checked here instead of
    handing chordtones.js more than it can decide.
    """
    if symbol == "N.C.":
        return True
    if not isinstance(symbol, str) or symbol != symbol.strip():
        return False
    base, slash, bass = symbol.partition("/")
    if slash and not PC.match(bass):
        return False
    shape = QUALITY.match(base)
    if not shape:
        return False
    # Each alteration at most once: "C7b9b9" is not a chord.
    alterations = re.findall(r"b5|#5|b9|#9|#11|b13", shape.group("alt"))
    return len(alterations) == len(set(alterations))


def _check_symbol(name, known, label, errors):
    if name == "N.C.":
        return
    if not isinstance(name, str) or not known.get(name) or not check_symbol(name):
        errors.append(f"{label} is not a parseable chord symbol")


def validate(obj, measurement):
    """Return (cleaned, errors). Times are snapped onto the engine grid."""
    errors = []
    if not isinstance(obj, dict):
        return {}, ["track.json is not a JSON object"]
    status = obj.get("status")
    if status not in ("chords", "needs_remeasure", "insufficient"):
        errors.append("status must be chords, needs_remeasure, or insufficient")
        return obj, errors

    bars = measurement.get("bars") or {}
    grid = measurement.get("grid") or {}
    times = allowed_times(bars)
    duration = float(measurement.get("duration") or grid.get("duration") or 0)
    chart_ok = bool(measurement.get("chart_verbatim") and measurement.get("chart"))
    candidates = measurement.get("candidates") if isinstance(measurement.get("candidates"), dict) else {}

    if status == "needs_remeasure":
        cleaned, more = _empty_status(obj, "needs_remeasure")
        errors.extend(more)
        errors.extend(_check_remeasure(obj.get("remeasure")))
        new_start = (obj.get("remeasure") or {}).get("bar_start") if isinstance(obj.get("remeasure"), dict) else None
        if new_start is not None and times and snap(new_start, times) is None:
            errors.append("remeasure.bar_start is not a bar or part time")
        return cleaned, errors
    if status == "insufficient":
        cleaned, more = _empty_status(obj, "insufficient")
        errors.extend(more)
        if obj.get("remeasure") not in (None, {}):
            errors.append("insufficient does not take remeasure")
        return cleaned, errors

    if not times:
        return obj, ["bars are missing, so chord times cannot be checked"]
    if obj.get("remeasure") not in (None, {}):
        errors.append("a chords result must not include remeasure")

    try:
        bpm = float(obj.get("bpm"))
    except (TypeError, ValueError):
        errors.append("bpm is missing")
        bpm = None
    else:
        if abs(bpm - float(grid.get("bpm"))) > 0.05:
            errors.append("bpm does not match grid.bpm")

    bar_start = snap(obj.get("bar_start"), times)
    if bar_start is None:
        errors.append("bar_start is not a bar or part time")

    beats = obj.get("beats_per_bar")
    usual = _usual_beats(bars)
    if beats != usual:
        errors.append(f"beats_per_bar must be {usual}")

    chart_used = obj.get("chart_used")
    if chart_used is not chart_ok:
        errors.append("chart_used does not match the chart that was supplied")

    chords_in = obj.get("chords")
    if not isinstance(chords_in, list) or not chords_in:
        errors.append("chords must list at least one event")
        chords_in = []

    symbols = []
    for chord in chords_in:
        if isinstance(chord, dict) and isinstance(chord.get("chord"), str):
            symbols.append(chord["chord"])
            if isinstance(chord.get("alternative"), str):
                symbols.append(chord["alternative"])
            for opt in chord.get("options") or []:
                if isinstance(opt, dict) and isinstance(opt.get("chord"), str):
                    symbols.append(opt["chord"])
    try:
        known = parse_ok(symbols)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return obj, [f"chord symbol check failed: {exc}"]

    chords = []
    for i, chord in enumerate(chords_in):
        label = f"chords[{i}]"
        if not isinstance(chord, dict):
            errors.append(f"{label} is not an object")
            continue
        t = snap(chord.get("t"), times)
        if t is None:
            errors.append(f"{label}.t is not a bar or part time")
        name = chord.get("chord")
        roman = chord.get("roman")
        conf = chord.get("conf")
        source = chord.get("source")
        if name is None:
            if roman is not None:
                errors.append(f"{label}.roman must be null when chord is null")
            if conf != "low" or source != "measured":
                errors.append(f"{label} with a null chord must be measured and low")
        elif name == "N.C.":
            if roman != "N.C.":
                errors.append(f"{label}.roman for N.C. must be N.C.")
        else:
            _check_symbol(name, known, f"{label}.chord", errors)
            if not isinstance(roman, str) or not roman:
                errors.append(f"{label}.roman is missing")
        if conf not in ("ok", "low"):
            errors.append(f"{label}.conf must be ok or low")
        if source not in ("chart", "measured"):
            errors.append(f"{label}.source must be chart or measured")
        if conf == "ok" and (source != "chart" or not chart_ok):
            errors.append(f"{label}.conf ok is only for a verbatim chart chord")
        if source == "measured" and conf == "ok":
            errors.append(f"{label} measured chord cannot be ok")
        if source == "chart" and not chart_ok:
            errors.append(f"{label}.source chart requires a verbatim chart")
        bass = chord.get("bass_pc")
        if bass is not None and not (isinstance(bass, str) and PC.match(bass)):
            errors.append(f"{label}.bass_pc is not a pitch class")
        if not isinstance(chord.get("why"), str) or not chord.get("why").strip():
            errors.append(f"{label}.why must be one sentence")
        scored = _candidates_at(candidates, chord.get("t"))
        alt = chord.get("alternative")
        if alt is not None:
            if alt not in scored:
                errors.append(f"{label}.alternative is not a candidate scored at this time (run a scoring tool with --save)")
            else:
                _check_symbol(alt, known, f"{label}.alternative", errors)
        opts = chord.get("options")
        if opts is not None:
            if not scored:
                errors.append(f"{label}.options need candidates scored at this time (run a scoring tool with --save)")
            elif conf != "low" or not isinstance(opts, list) or not 2 <= len(opts) <= 3:
                errors.append(f"{label}.options must be 2 or 3 choices on a low chord")
            else:
                for j, opt in enumerate(opts):
                    if not isinstance(opt, dict):
                        errors.append(f"{label}.options[{j}] is not an object")
                        continue
                    _check_symbol(opt.get("chord"), known, f"{label}.options[{j}].chord", errors)
                    if opt.get("chord") != name and opt.get("chord") not in scored:
                        errors.append(f"{label}.options[{j}] is neither the chord nor a candidate scored at this time")
                if name and isinstance(opts[0], dict) and opts[0].get("chord") != name:
                    errors.append(f"{label}.options[0] must equal the chord")
        chords.append({
            "t": t,
            "chord": name,
            "roman": roman,
            "conf": conf,
            "source": source,
            "bass_pc": bass,
            "alternative": alt,
            "why": chord.get("why"),
            "options": opts,
        })

    sections, section_errors = _sections(obj.get("sections"), bar_start, duration)
    errors.extend(section_errors)
    keys, key_errors = _keys(obj, times, bar_start)
    errors.extend(key_errors)

    cleaned = {
        "status": "chords",
        "key": obj.get("key"),
        "keys": keys,
        "bpm": None if bpm is None else float(grid.get("bpm")),
        "bar_start": bar_start,
        "beats_per_bar": usual,
        "sections": sections,
        "chords": chords,
        "remeasure": None,
        "bleed_stems": obj.get("bleed_stems") if isinstance(obj.get("bleed_stems"), list) else [],
        "chart_used": chart_ok,
        "notes": obj.get("notes") if isinstance(obj.get("notes"), list) else [],
    }
    if not isinstance(cleaned["key"], str) or not cleaned["key"].strip():
        errors.append("key is missing")
    return cleaned, errors


def _empty_status(obj, status):
    errors = []
    if obj.get("chords") not in (None, []):
        errors.append(f"{status} must not include chords")
    if obj.get("sections") not in (None, []):
        errors.append(f"{status} must not include sections")
    notes = obj.get("notes") if isinstance(obj.get("notes"), list) else []
    cleaned = {
        "status": status,
        "key": obj.get("key"),
        "keys": [],
        "bpm": obj.get("bpm"),
        "bar_start": obj.get("bar_start"),
        "beats_per_bar": obj.get("beats_per_bar"),
        "sections": [],
        "chords": [],
        "remeasure": obj.get("remeasure") if status == "needs_remeasure" else None,
        "bleed_stems": obj.get("bleed_stems") if isinstance(obj.get("bleed_stems"), list) else [],
        "chart_used": bool(obj.get("chart_used")),
        "notes": notes,
    }
    return cleaned, errors


def _check_remeasure(spec):
    errors = []
    if not isinstance(spec, dict):
        return ["remeasure must be an object"]
    if not isinstance(spec.get("reason"), str) or not spec.get("reason").strip():
        errors.append("remeasure.reason is missing")
    if spec.get("bar_start") is not None:
        try:
            if float(spec["bar_start"]) < 0:
                errors.append("remeasure.bar_start is negative")
        except (TypeError, ValueError):
            errors.append("remeasure.bar_start is not a number")
    if spec.get("split") is not None:
        try:
            if not 1 <= int(spec["split"]) <= 8:
                errors.append("remeasure.split must be from 1 to 8")
        except (TypeError, ValueError):
            errors.append("remeasure.split is not an integer")
    for i, row in enumerate(spec.get("short_bars") or []):
        if not isinstance(row, dict):
            errors.append(f"remeasure.short_bars[{i}] is not an object")
            continue
        try:
            bar, beats = int(row["bar"]), int(row["beats"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"remeasure.short_bars[{i}] needs bar and beats")
            continue
        if bar < 1 or not 1 <= beats <= 12:
            errors.append(f"remeasure.short_bars[{i}] is out of range")
    return errors


def _sections(sections, bar_start, duration):
    if not isinstance(sections, list) or not sections:
        return [], ["sections must partition the song"]
    rows = []
    errors = []
    for i, row in enumerate(sections):
        if not isinstance(row, dict) or not row.get("name"):
            errors.append(f"sections[{i}] needs a name")
            continue
        try:
            start, end = float(row["start"]), float(row["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"sections[{i}] needs start and end")
            continue
        rows.append({"name": str(row["name"]), "start": start, "end": end})
    if not rows or bar_start is None:
        return rows, errors
    starts = [row["start"] for row in rows]
    if starts != sorted(starts):
        errors.append("sections must be in time order")
    if abs(rows[0]["start"] - bar_start) > TIME_TOL:
        errors.append("the first section must start at bar_start")
    for left, right in zip(rows, rows[1:]):
        if abs(left["end"] - right["start"]) > TIME_TOL:
            errors.append(f"sections {left['name']} and {right['name']} leave a gap or overlap")
    if abs(rows[-1]["end"] - float(duration)) > TIME_TOL:
        errors.append("the last section must end at duration")
    return rows, errors


def _keys(obj, times, bar_start):
    raw = obj.get("keys")
    if not raw:
        if bar_start is None or not obj.get("key"):
            return [], []
        return [{"t": bar_start, "key": obj.get("key")}], []
    if not isinstance(raw, list):
        return [], ["keys must be a list"]
    rows, errors = [], []
    for i, row in enumerate(raw):
        if not isinstance(row, dict) or not row.get("key"):
            errors.append(f"keys[{i}] needs a key")
            continue
        t = snap(row.get("t"), times)
        if t is None:
            errors.append(f"keys[{i}].t is not a bar or part time")
        rows.append({"t": t, "key": row.get("key")})
    return rows, errors
