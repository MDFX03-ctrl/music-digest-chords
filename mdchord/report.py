"""Skeleton analysis in the digest template. Ear verification is still open."""


def _bars_for(section, bars):
    start, end = section["start"], section["end"]
    nums = [bar["bar"] for bar in bars if start - 0.05 <= float(bar["t"]) < end - 0.05]
    if not nums:
        return ""
    if len(nums) == 1:
        return str(nums[0])
    return f"{nums[0]}–{nums[-1]}"


def write_analysis(track, bars, title, artist, chart_name):
    lines = [
        f"# {artist + ' – ' if artist else ''}{title or 'Untitled'}",
        "",
        "**Songwriter(s):**",
        f"**Sources:** chart file: {chart_name or 'none supplied'}",
        "**Status:** ⏳ first pass. Melody is paused. Not verified by ear.",
        "",
        "### 1. Key & tempo",
        "| Key(s) | Tempo | Meter | Confidence |",
        "|---|---|---|---|",
        f"| {track.get('key')} | {track.get('bpm')} BPM | {track.get('beats_per_bar')}/4 | measured, ⏳ |",
        "",
        "### 2. Chord map",
        "| Section [bars] | Chords | Roman numerals | Key | Status |",
        "|---|---|---|---|---|",
    ]
    chords = track.get("chords") or []
    for section in track.get("sections") or []:
        span = [c for c in chords if section["start"] - 0.05 <= float(c["t"]) < section["end"] - 0.05]
        symbols = " ".join(c["chord"] or "?" for c in span) or "—"
        romans = " ".join(c["roman"] or "?" for c in span) or "—"
        bars_label = _bars_for(section, bars)
        name = section["name"] + (f" [{bars_label}]" if bars_label else "")
        lines.append(f"| {name} | {symbols} | {romans} | {track.get('key')} | ⏳ |")
    lines += [
        "",
        "### 3. Section notes",
        "",
        "Added when a section is verified by ear.",
        "",
        "*Melody (paused).*",
        "",
    ]
    if track.get("notes"):
        lines.append("### Measurement notes")
        lines.append("")
        for note in track["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    low = [c for c in chords if c.get("conf") == "low"]
    if low:
        lines.append("### Low confidence")
        lines.append("")
        for chord in low:
            alt = ""
            if chord.get("options"):
                alt = " Options: " + ", ".join(o["chord"] for o in chord["options"])
            lines.append(f"- {chord['t']}: {chord.get('chord') or 'null'}. {chord.get('why') or ''}{alt}")
        lines.append("")
    return "\n".join(lines)
