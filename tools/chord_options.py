#!/usr/bin/env python3
"""Rank candidate chords for uncertain spots, from the stems (for option cards in Chord Follower).

Usage: python3 chord_options.py <track.json> <stems dir> <stem offset> <chord index> [<chord index> ...]
                                 [--save <measurement.json>]
Prints JSON: {index: [{chord, score, bass_ok}, ...]} (best first). The current chart chord is always scored too.
--save records the candidates in measurement.json, keyed by chord time, so `check` accepts them as options.
Score = cosine match between the chord's pitch classes and the harmonic stems' chroma
(overtones of lower notes removed), plus a bonus when the chord's bass note is the strongest low note.
The top candidates are *measured suggestions*; the user picks by ear.
"""
import json, os, subprocess, sys
import numpy as np, librosa

args = sys.argv[1:]
save_to = None
if '--save' in args:
    at = args.index('--save'); save_to = args[at + 1]; del args[at:at + 2]
track, sdir, off = args[0], args[1], float(args[2])
idxs = [int(x) for x in args[3:]]
T = json.load(open(track)); T = T.get('data', T); ch = T['chords']
here = os.path.dirname(os.path.abspath(__file__))
ROOTS = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']
QUAL = ['', 'm', '7', 'maj7', 'm7', 'sus2', 'sus4', 'add9', '6', 'm7b5', 'dim']
syms = [r + q for r in ROOTS for q in QUAL] + [ch[i]['chord'] for i in idxs]
P = json.loads(subprocess.check_output(['node', '-e',
    f"const CT=require({json.dumps(os.path.join(here,'chordtones.js'))});const o={{}};for(const s of {json.dumps(syms)})o[s]=CT.parse(s);console.log(JSON.stringify(o))"]))

SR, HOP, LO, NB = 22050, 512, 24, 72
def load(n):
    p = os.path.join(sdir, n + '.wav')
    return librosa.load(p, sr=SR, mono=True)[0] if os.path.exists(p) else None
harm = sum(x for x in (load('piano'), load('guitar'), load('other')) if x is not None)
bass = load('bass'); low = harm + (bass if bass is not None else 0)
Ch = np.abs(librosa.cqt(harm, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
Cl = np.abs(librosa.cqt(low, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
fr = lambda t: int(max(0, t) * SR / HOP)

def unpartial(x, src):
    y = x.copy(); src = np.maximum(src, x)
    for k in range(NB):
        for d, w in ((12, .5), (19, .35), (24, .25), (28, .15)):
            if k - d >= 0: y[k] = max(0.0, y[k] - w * src[k - d])
    return y

out = {}
for i in idxs:
    t1 = ch[i+1]['t'] if i + 1 < len(ch) else T['duration']
    a, b = fr(ch[i]['t'] + off), fr(t1 + off)
    Eh = unpartial(Ch[:, a:b].mean(1), Cl[:, a:b].mean(1)); El = Cl[:, a:b].mean(1)
    chroma = np.zeros(12)
    for k in range(NB): chroma[(LO + k) % 12] += Eh[k]
    chroma /= np.linalg.norm(chroma) + 1e-9
    lowpc = int(np.argmax([sum(El[k] for k in range(4, 29) if (LO + k) % 12 == pc) for pc in range(12)]))
    res, seen = [], set()
    cur = ch[i]['chord']
    for s0 in [cur] + [r + q for r in ROOTS for q in QUAL]:
        p = P.get(s0)
        if not p: continue
        base = s0.split('/')[0]
        sym = s0 if '/' in s0 else (base + '/' + ROOTS[lowpc] if (lowpc in p['pcs'] and lowpc != p['root']) else base)
        bass = lowpc if lowpc in p['pcs'] else p['bass']
        key = (frozenset(p['pcs']), bass)
        if key in seen: continue
        seen.add(key)
        tpl = np.zeros(12); tpl[p['pcs']] = 1; tpl[p['root']] += 0.5
        sc = float(tpl @ chroma / np.linalg.norm(tpl)) + (0.08 if lowpc in p['pcs'] else 0)
        res.append({'chord': sym, 'score': round(sc, 3), 'bass_ok': lowpc in p['pcs'], 'is_current': s0 == cur})
    res.sort(key=lambda r: -r['score'])
    top = res[:6]
    cur = ch[i]['chord']
    out[i] = {'current': cur, 'low': ROOTS[lowpc], 'candidates': top,
              'current_score': next((r['score'] for r in res if r['is_current']), None)}
print(json.dumps(out, indent=1))
if save_to:
    from save_candidates import save
    save(save_to, {ch[i]['t']: out[i]['candidates'] for i in idxs})
    print(f"saved candidates to {save_to}")
