"""Build the measurement object described in prompts/chord-naming.md."""

import json


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def measurement(manifest, grid, bars, chart, duration, candidates=None):
    text = (chart or "").strip()
    return {
        "manifest": manifest,
        "grid": grid,
        "bars": bars,
        "chart": text or None,
        "chart_verbatim": bool(text),
        "candidates": candidates,
        "duration": duration,
    }


def remeasure_plan(spec, start, split):
    """Return (start, split, short args) or None when the request changes nothing."""
    if not isinstance(spec, dict):
        return None
    new_start = spec.get("bar_start")
    new_split = spec.get("split")
    shorts = []
    for row in spec.get("short_bars") or []:
        shorts.append(f"{int(row['bar'])}:{int(row['beats'])}")
    start2 = float(start if new_start is None else new_start)
    split2 = int(split if new_split is None else new_split)
    if abs(start2 - float(start)) <= 1e-3 and split2 == int(split) and not shorts:
        return None
    if not 1 <= split2 <= 8:
        raise ValueError(f"split {split2} is outside 1..8")
    if start2 < 0:
        raise ValueError("bar_start is negative")
    return start2, split2, shorts
