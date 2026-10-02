"""Record scored chords in measurement.json `candidates`, keyed by chord time.

Shared by chord_options.py and score_candidates.py (--save). `check` accepts an
option only when it is the chord itself or a candidate recorded for that time.
"""
import json


def time_key(t):
    """"4" for 4 or 4.0, "4.5" for 4.5: one key per time however it was written."""
    return f"{float(t):g}"


def save(path, scored):
    """scored: {time: [{chord, score, bass_ok}, ...]}. Same chord at a time is replaced."""
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    found = data.get("candidates") if isinstance(data.get("candidates"), dict) else {}
    for t, rows in scored.items():
        key = time_key(t)
        merged = {row["chord"]: row for row in found.get(key) or [] if isinstance(row, dict) and row.get("chord")}
        for row in rows:
            merged[row["chord"]] = {"chord": row["chord"], "score": row["score"], "bass_ok": bool(row["bass_ok"])}
        found[key] = sorted(merged.values(), key=lambda row: -row["score"])
    data["candidates"] = found
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return found
