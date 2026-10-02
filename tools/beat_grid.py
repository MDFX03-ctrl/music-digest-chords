#!/usr/bin/env python3
"""Music Digest: tempo, beat phase and downbeat for a song, from its stems.

Usage: python3 beat_grid.py <stems dir> [--bpm-min 60 --bpm-max 140] [--out grid.json]

What it does (the method used for the MISIA digest, 2026-09-29):
 1. Fixed-tempo fit. Onset strength of drums + 0.5*bass (hop 128 = 5.8 ms). librosa's first
    guess and its related levels (x1/2, x2, x2/3, x3/2, x3/4, x4/3) inside --bpm-min..--bpm-max
    are each fitted: BPM in 0.01 steps and phase in 5 ms steps, keeping the grid whose beat
    positions have the highest mean onset strength over the WHOLE song. Studio tracks on a
    click fit one exact BPM. (librosa.beat.beat_track is NOT used for the final grid: it
    quantises to frames, drifts and slips phase in quiet sections.)
    The level is then chosen by a strength-weighted F-measure of grid beats against detected
    onsets, not by mean strength (which always prefers half tempo on loud downbeats). Between a
    level and its double, the in-between positions decide: a backbeat (>= 0.85 of the beat's
    strength) means the faster level, weaker hats mean the slower one. The other levels and
    their scores are printed; force one with --bpm-min/--bpm-max.
 2. Phase check per 20-s window for drums, guitar, bass and the harmonic stems. A stable
    offset between stems is normal (e.g. guitar accenting the 16th before the beat); a
    window whose phase jumps by ~half a bar-unit points to a meter change (2/4 bar).
 3. Downbeat candidates. Chords usually change on beat 1 (and 3). The script counts
    bass-pitch changes by beat position mod 4 and prints which positions carry them.
    Decide the final downbeat with bar_report.py (harmonic rhythm + section starts),
    never from this count alone.
Prints a report and writes grid.json {bpm, beat_phase, period, windows, change_counts}.
"""
import argparse, json, os
import numpy as np, librosa
from scipy.ndimage import maximum_filter1d

ap = argparse.ArgumentParser()
ap.add_argument('stems'); ap.add_argument('--bpm-min', type=float, default=60)
ap.add_argument('--bpm-max', type=float, default=140); ap.add_argument('--out', default='grid.json')
a = ap.parse_args()
SR = 22050
L = lambda n: librosa.load(os.path.join(a.stems, n + '.wav'), sr=SR, mono=True)[0] if os.path.exists(os.path.join(a.stems, n + '.wav')) else None
dr, ba, gu, pi, ot = (L(n) for n in ('drums', 'bass', 'guitar', 'piano', 'other'))
z = lambda x: x if x is not None else 0
if dr is None and ba is None:
    raise SystemExit(f"beat_grid: no drums or bass stem in {a.stems}; the tempo fit needs one")
if ba is None and gu is None and pi is None and ot is None:
    raise SystemExit(f"beat_grid: no bass, guitar, piano or other stem in {a.stems}; change_counts needs one")
harm = None if gu is None and pi is None and ot is None else z(gu) + z(pi) + z(ot)
dur = max(len(x) for x in (dr, ba, gu, pi, ot) if x is not None) / SR

def onset(y, hop=128):
    return librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop), SR / hop

o, fr = onset(z(dr) + 0.5 * z(ba))
# 1. coarse tempo from autocorrelation-based estimate, then fine scan around it
t0 = float(librosa.feature.tempo(onset_envelope=o, sr=SR, hop_length=128, start_bpm=90)[0])
lo, hi = a.bpm_min, a.bpm_max
# librosa can land on the wrong metrical level (half, double, or 2:3 off), so
# every related level in range is tried.
cands = sorted({round(t0 * r, 2) for r in (1, 1/2, 2, 2/3, 3/2, 3/4, 4/3) if lo <= t0 * r <= hi})
if not cands:
    raise SystemExit(f"beat_grid: librosa's tempo {t0:.1f} BPM has no related tempo in "
                     f"{lo:g}-{hi:g}; widen --bpm-min/--bpm-max")

def fit(c):
    """Exact bpm and phase near c: the grid with the highest mean onset strength."""
    best = None
    for bpm in np.arange(c - 1.5, c + 1.5, 0.01):
        p = 60 / bpm
        for ph in np.arange(0, p, 0.005):
            t = np.arange(ph, dur - 1, p); s = o[(t * fr).astype(int)].mean()
            if best is None or s > best[0]: best = (float(s), float(bpm), float(ph))
    return best[1], best[2]

# Choosing BETWEEN levels by mean onset is biased: a half-tempo grid sits only
# on the louder downbeats and wins (120 read as 60). Score each level instead as
# a strength-weighted F-measure of grid beats against detected onsets:
#   recall    = share of onset strength the grid lands on (too slow skips hits)
#   precision = how strong the onset at each grid beat is (too fast lands on gaps)
TOL = 0.07
peaks = librosa.onset.onset_detect(onset_envelope=o, sr=SR, hop_length=128)
ref = float(np.percentile(o[peaks], 90)) if len(peaks) else float(o.max()) or 1.0
near = maximum_filter1d(o, size=2 * int(TOL * fr) + 1)   # strongest onset within TOL of each frame

def level_score(bpm, ph):
    p = 60 / bpm
    t = np.arange(ph, dur - 1, p)
    precision = float(np.minimum(1, near[(t * fr).astype(int)] / ref).mean())
    if not len(peaks):
        return precision
    off = (peaks / fr - ph) % p
    hit = np.minimum(off, p - off) <= TOL
    recall = float(o[peaks][hit].sum() / o[peaks].sum())
    return 2 * precision * recall / (precision + recall + 1e-9)

levels = []
for c in cands:
    b, p0 = fit(c)
    levels.append((level_score(b, p0), b, p0))
levels.sort(reverse=True)

# The F-measure settles 2:3 and 3:4 confusions, but not double vs half: weak
# 8th-note hats count as hits, so a 70 BPM ballad scores well at 140. Between a
# level and its double, the in-between positions decide. A backbeat (snare on
# 2 and 4) is about as strong as the beat; a subdivision (hats) is clearly weaker.
BACKBEAT = 0.85

def in_between_ratio(bpm, ph):
    t = np.arange(ph, dur - 1, 60 / bpm); v = near[(t * fr).astype(int)]
    on, off = v[0::2].mean(), v[1::2].mean()
    return float(min(on, off) / (max(on, off) + 1e-9))

top = levels[0]
for s, b, p0 in levels[1:]:
    fast, slow = (top, (s, b, p0)) if top[1] > b else ((s, b, p0), top)
    if abs(fast[1] / slow[1] - 2) > 0.02:
        continue
    ratio = in_between_ratio(fast[1], fast[2])
    top = fast if ratio >= BACKBEAT else slow
    print(f"double/half check {slow[1]:.2f} vs {fast[1]:.2f}: in-between strength {ratio:.2f} "
          f"({'backbeat' if ratio >= BACKBEAT else 'subdivision'}, threshold {BACKBEAT})")
    break
levels.remove(top); levels.insert(0, top)
_, bpm, ph = levels[0]; P = 60 / bpm
print(f"tempo {bpm:.2f} BPM (beat {P:.4f} s), beat phase {ph:.3f} s  [librosa first guess {t0:.1f}]")
if len(levels) > 1:
    print("other tempo levels (score; force one with --bpm-min/--bpm-max): "
          + ", ".join(f"{b:.2f} ({s:.2f})" for s, b, _ in levels[1:]) + f"; chosen {levels[0][0]:.2f}")

# 2. phase per 20-s window per stem
def window_phase(y):
    if y is None: return None
    oo, f = onset(y, 64); out = []
    for w0 in range(0, int(dur) - 5, 20):
        bb = None
        for q in np.arange(0, P, 0.005):
            t = np.arange(q, dur, P); t = t[(t >= w0) & (t < w0 + 20)]
            if not len(t): continue
            s = oo[(t * f).astype(int)].mean()
            if bb is None or s > bb[0]: bb = (s, q)
        out.append(round(float(bb[1]), 3) if bb else None)
    return out
win = {n: window_phase(y) for n, y in (('drums', dr), ('bass', ba), ('guitar', gu), ('harm', harm))}
print('window phase (s) every 20 s:')
for n, v in win.items():
    if v: print(f"  {n:6s} " + ' '.join(f"{x:.2f}" for x in v))

# 3. bass pitch per beat -> where do changes fall (mod 4)?
HOP = 512
src = ba if ba is not None else harm
Cb = np.abs(librosa.cqt(src, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(28), n_bins=24))
k, pcs = 0, []
while ph + P * (k + 1) < dur:
    s, e = int((ph + P * k) * SR / HOP), int((ph + P * (k + 1)) * SR / HOP)
    v = Cb[:, s:e].mean(1); pc = np.zeros(12)
    for i in range(24): pc[(28 + i) % 12] += v[i]
    pcs.append(int(np.argmax(pc))); k += 1
cnt = [0] * 4
for i in range(1, len(pcs)):
    if pcs[i] != pcs[i - 1]: cnt[i % 4] += 1
print('bass changes by beat index mod 4:', cnt, '(beat index 0 = first beat at phase)')
json.dump({'bpm': round(bpm, 2), 'beat_phase': round(ph, 3), 'period': P, 'duration': dur,
           'windows': win, 'change_counts': cnt}, open(a.out, 'w'), indent=1)
