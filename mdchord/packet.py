"""Build the measurement object described in prompts/chord-naming.md."""

import json


def load_json(path):
    # utf-8-sig so a track.json saved by an editor that writes a BOM (Notepad
    # on Windows does) still parses instead of failing on char 0.
    with open(path, encoding="utf-8-sig") as f:
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
