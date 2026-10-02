"""Attach measured option cards. Symbols come from chord_options.py, not from the model."""


def attach_options(chords, scored):
    """scored is chord_options.py's object, keyed by chord index."""
    for i, chord in enumerate(chords):
        if chord.get("conf") != "low" or chord.get("options"):
            continue
        block = (scored or {}).get(str(i)) or {}
        pool = []
        for cand in block.get("candidates") or []:
            name = cand.get("chord")
            if name and name != chord.get("chord") and name not in pool:
                pool.append((bool(cand.get("bass_ok")), name))
        preferred = [name for ok, name in pool if ok] or [name for _, name in pool]
        current = chord.get("chord")
        if not current or not preferred:
            continue
        chord["options"] = [{"chord": current, "roman": chord.get("roman") or "?"}]
        for name in preferred[:2]:
            chord["options"].append({"chord": name, "roman": "?"})
    return chords
