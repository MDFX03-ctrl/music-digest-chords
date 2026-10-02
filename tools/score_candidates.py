#!/usr/bin/env python3
"""Score YOUR candidate chords at chosen chart positions (for option cards), instead of the full ranking.

Usage: python3 score_candidates.py <track.json> <stems dir> <stem offset> '<{"idx": ["A","A7sus4","Asus4"], ...}>'
Prints per chord index: current chord, strongest low note, each candidate's score, and the top-6 chroma.
Same measure as chord_options.py (harmonic stems, overtones of lower notes removed, +0.08 when the chord
contains the lowest note). Use it when chord_options.py's ranking is swamped by a drone (MISIA: open D/A strings
made every chord rank as a D chord) and you need to compare the chart chord with 2-3 specific alternatives.
Scores are evidence, not verdicts: the user's ear decides (MISIA verse "A" scored 0.55 vs A7sus4 0.80; ear chose A).
Tip: to score part of a chord (e.g. a 2/4 bar inside a held chord), insert a temporary chord entry at that time.
"""
import json, os, subprocess, sys
import numpy as np, librosa
T = json.load(open(sys.argv[1])); T = T.get('data', T); ch = T['chords']
sdir, off, spec = sys.argv[2], float(sys.argv[3]), json.loads(sys.argv[4])
here = os.path.dirname(os.path.abspath(__file__))
syms = sorted({s for v in spec.values() for s in v})
P = json.loads(subprocess.check_output(['node', '-e',
    f"const CT=require({json.dumps(os.path.join(here, 'chordtones.js'))});const o={{}};for(const s of {json.dumps(syms)})o[s]=CT.parse(s);console.log(JSON.stringify(o))"]))
SR, HOP, LO, NB = 22050, 512, 24, 72
def L(n):
    p = os.path.join(sdir, n + '.wav')
    return librosa.load(p, sr=SR, mono=True)[0] if os.path.exists(p) else None
harm = sum(x for x in (L('piano'), L('guitar'), L('other')) if x is not None)
bass = L('bass'); low = harm + (bass if bass is not None else 0)
Ch = np.abs(librosa.cqt(harm, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
Cl = np.abs(librosa.cqt(low, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
fr = lambda t: int(max(0, t) * SR / HOP)
def unp(x, src):
    y = x.copy(); src = np.maximum(src, x)
    for k in range(NB):
        for d, w in ((12, .5), (19, .35), (24, .25), (28, .15)):
            if k - d >= 0: y[k] = max(0, y[k] - w * src[k - d])
    return y
N = 'C Db D Eb E F Gb G Ab A Bb B'.split()
for i, cands in spec.items():
    i = int(i); t1 = ch[i + 1]['t'] if i + 1 < len(ch) else T['duration']
    a, b = fr(ch[i]['t'] + off), fr(t1 + off)
    Eh = unp(Ch[:, a:b].mean(1), Cl[:, a:b].mean(1)); El = Cl[:, a:b].mean(1)
    cr = np.zeros(12)
    for k in range(NB): cr[(LO + k) % 12] += Eh[k]
    cr /= np.linalg.norm(cr) + 1e-9
    lowpc = int(np.argmax([sum(El[k] for k in range(4, 29) if (LO + k) % 12 == pc) for pc in range(12)]))
    out = []
    for s in cands:
        p = P[s]; tpl = np.zeros(12); tpl[p['pcs']] = 1; tpl[p['root']] += .5
        out.append(f"{s} {tpl @ cr / np.linalg.norm(tpl) + (0.08 if lowpc in p['pcs'] else 0):.3f}")
    top = ' '.join(f"{N[j]}{cr[j]:.2f}" for j in np.argsort(-cr)[:6])
    print(i, ch[i]['t'], ch[i]['chord'], 'low', N[lowpc], '|', ', '.join(out), '| chroma', top)
