#!/usr/bin/env python3
"""Music Digest: bar-by-bar report of a song from its stems (sections, bass line, harmony).

Usage: python3 bar_report.py <stems dir> <mix audio> <bpm> <first downbeat s>
                             [--beats 4] [--split 2] [--short 21:2 ...] [--out bars.json]
  --split  : readings per bar (2 = half bars; use the song's harmonic rhythm)
  --short  : a bar with a different beat count, e.g. 21:2 = bar 21 is 2/4 (repeatable)

Per bar it prints: start time, dB level of mix / vocals / drums / bass stems, and per split:
  bass pitch class (bass stem CQT E1–D#3) / lowest harmonic note (guitar+piano+other, C2–B3)
  : top-4 chroma of the harmonic stems.
Also prints the key (Krumhansl-Schmuckler on harmonic+bass chroma) and tuning offset.

How to read it (lessons from the MISIA digest, 2026-09-29):
 - SECTIONS come from stem levels: vocals in/out, drums in/out, bass in/out, plus where the
   chord pattern restarts. Put boundaries on bar lines.
 - The BASS column is the most reliable chord evidence. When the bass stem is silent
   (< about -60 dB) use the lowest harmonic note instead.
 - CHROMA top-4 is biased by sustained notes: open-string drones (e.g. guitar D and A ringing
   under every chord) make every chord read as a D chord / "D pedal". Never name chords from
   chroma alone: combine bass + chroma + the source chart, then test with chord_options.py.
 - METER CHANGES: if the chord pattern that was on the downbeat suddenly lands half a bar
   later from some point on (bass pattern shifts by 2 beats), there is a 2/4 (or 6/4) bar
   just before it. Confirm with a drum fill/level change there, then re-run with --short.
   Chord Follower has one fixed grid: set barStart so the longest part of the song is on
   the grid (bar numbers stay right; beat counts are off before the odd bar) and say so
   in the track note.
"""
import argparse, json, os
import numpy as np, librosa

ap = argparse.ArgumentParser()
ap.add_argument('stems'); ap.add_argument('mix'); ap.add_argument('bpm', type=float); ap.add_argument('start', type=float)
ap.add_argument('--beats', type=int, default=4); ap.add_argument('--split', type=int, default=2)
ap.add_argument('--short', action='append', default=[]); ap.add_argument('--out', default='bars.json')
a = ap.parse_args()
SR, HOP = 22050, 512
N = 'C Db D Eb E F Gb G Ab A Bb B'.split()
def L(n):
    p = os.path.join(a.stems, n + '.wav')
    return librosa.load(p, sr=SR, mono=True)[0] if os.path.exists(p) else None
vo, dr, ba = L('vocals'), L('drums'), L('bass')
hs = [x for x in (L('guitar'), L('piano'), L('other')) if x is not None]
if not hs:
    raise SystemExit(f"bar_report: no guitar, piano or other stem in {a.stems}; chroma and the low note need one")
harm = sum(hs)
mix = librosa.load(a.mix, sr=SR, mono=True)[0]
dur = len(mix) / SR

# key + tuning
tun = librosa.estimate_tuning(y=harm, sr=SR)
C = librosa.feature.chroma_cqt(y=harm + (ba if ba is not None else 0), sr=SR, tuning=tun)
prof = C.mean(1)
MAJ = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]); MIN = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
ks = sorted([(np.corrcoef(np.roll(MAJ, i), prof)[0,1], N[i] + ' major') for i in range(12)] +
            [(np.corrcoef(np.roll(MIN, i), prof)[0,1], N[i] + ' minor') for i in range(12)], reverse=True)
print(f"key: {ks[0][1]} (r={ks[0][0]:.2f}; next {ks[1][1]} {ks[1][0]:.2f}) · tuning {tun*100:+.0f} cents")

Cb = np.abs(librosa.cqt(ba if ba is not None else harm, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(28), n_bins=24, tuning=tun))
Cg = np.abs(librosa.cqt(harm, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(36), n_bins=24, tuning=tun))
Ch = librosa.feature.chroma_cqt(y=harm, sr=SR, hop_length=HOP, tuning=tun)
fr = lambda t: int(t * SR / HOP)
db = lambda y, s, e: float(20 * np.log10(np.sqrt(np.mean(y[int(s*SR):int(e*SR)] ** 2)) + 1e-9)) if y is not None else None
short = {int(x.split(':')[0]): int(x.split(':')[1]) for x in a.short}
beat = 60 / a.bpm
bars, t, n = [], a.start, 1
while t < dur - 0.5:
    nb = short.get(n, a.beats); e = min(t + nb * beat, dur)
    sp = max(1, round(a.split * nb / a.beats)); parts = []
    for j in range(sp):
        s0, s1 = t + (e - t) * j / sp, t + (e - t) * (j + 1) / sp
        bv = Cb[:, fr(s0):fr(s1)].mean(1); gv = Cg[:, fr(s0):fr(s1)].mean(1); cv = Ch[:, fr(s0):fr(s1)].mean(1)
        bp = np.zeros(12); gp = np.zeros(12)
        for i in range(24): bp[(28 + i) % 12] += bv[i]; gp[(36 + i) % 12] += gv[i]
        parts.append({'t': round(s0, 2), 'bass': N[int(np.argmax(bp))], 'low': N[int(np.argmax(gp))],
                      'chroma': [N[i] for i in np.argsort(-cv)[:4]]})
    row = {'bar': n, 't': round(t, 2), 'beats': nb, 'mix': db(mix, t, e), 'vox': db(vo, t, e), 'drums': db(dr, t, e), 'bassdb': db(ba, t, e), 'parts': parts}
    bars.append(row)
    f = lambda v: f"{v:4.0f}" if v is not None else '   -'
    ps = '  '.join(f"{p['bass']:>2}/{p['low']:<2}:{' '.join(p['chroma']):<12}" for p in parts)
    print(f"{n:3d} {t:7.2f}{'*' if nb != a.beats else ' '} mix{f(row['mix'])} vox{f(row['vox'])} dr{f(row['drums'])} bs{f(row['bassdb'])}  {ps}")
    t, n = e, n + 1
json.dump({'key': ks[0][1], 'tuning_cents': round(tun * 100), 'bpm': a.bpm, 'start': a.start, 'bars': bars}, open(a.out, 'w'), indent=1)
