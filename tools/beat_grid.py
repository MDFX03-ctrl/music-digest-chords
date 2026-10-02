#!/usr/bin/env python3
"""Music Digest: tempo, beat phase and downbeat for a song, from its stems.

Usage: python3 beat_grid.py <stems dir> [--bpm-min 60 --bpm-max 140] [--out grid.json]

What it does (the method used for the MISIA digest, 2026-09-29):
 1. Fixed-tempo fit. Onset strength of drums + 0.5*bass (hop 128 = 5.8 ms). Scan BPM in
    0.01 steps and phase in 5 ms steps; keep the grid whose beat positions have the highest
    mean onset strength over the WHOLE song. Studio tracks on a click fit one exact BPM.
    (librosa.beat.beat_track is NOT used for the final grid: it quantises to frames, drifts
    and slips phase in quiet sections.)
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

ap = argparse.ArgumentParser()
ap.add_argument('stems'); ap.add_argument('--bpm-min', type=float, default=60)
ap.add_argument('--bpm-max', type=float, default=140); ap.add_argument('--out', default='grid.json')
a = ap.parse_args()
SR = 22050
L = lambda n: librosa.load(os.path.join(a.stems, n + '.wav'), sr=SR, mono=True)[0] if os.path.exists(os.path.join(a.stems, n + '.wav')) else None
dr, ba, gu, pi, ot = (L(n) for n in ('drums', 'bass', 'guitar', 'piano', 'other'))
z = lambda x: x if x is not None else 0
harm = z(gu) + z(pi) + z(ot)
dur = max(len(x) for x in (dr, ba, gu) if x is not None) / SR

def onset(y, hop=128):
    return librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop), SR / hop

o, fr = onset(z(dr) + 0.5 * z(ba))
# 1. coarse tempo from autocorrelation-based estimate, then fine scan around it
t0 = float(librosa.feature.tempo(onset_envelope=o, sr=SR, hop_length=128, start_bpm=90)[0])
cands = [t0, t0 / 2, t0 * 2]
lo, hi = a.bpm_min, a.bpm_max
best = None
for c in cands:
    if not (lo <= c <= hi): continue
    for bpm in np.arange(c - 1.5, c + 1.5, 0.01):
        p = 60 / bpm
        for ph in np.arange(0, p, 0.005):
            t = np.arange(ph, dur - 1, p); s = o[(t * fr).astype(int)].mean()
            if best is None or s > best[0]: best = (float(s), float(bpm), float(ph))
_, bpm, ph = best; P = 60 / bpm
print(f"tempo {bpm:.2f} BPM (beat {P:.4f} s), beat phase {ph:.3f} s  [librosa first guess {t0:.1f}]")

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
