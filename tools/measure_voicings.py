#!/usr/bin/env python3
"""Measure piano voicings for a chord chart from the song's stems, with smooth voice leading.

Usage: python3 measure_voicings.py <track.json> <stems dir> <stem offset> <out.json>
  track.json : Chord Follower track doc (needs chords [{t, chord}], duration)
  stems dir  : folder with piano/guitar/other/bass .wav (from stems_for_daw.py)
  stem offset: stem time - chart time (same as the stems' `offset`)

1. Measure (per chord): only the chart's own chord tones are used. The stems decide
   which chord tones the song voices, the register of the top note, and the bass octave.
2. Voice-lead (whole song): the voicings are then chosen together so they stay stable
   instead of jumping. Rule: keep common tones, move other voices by the smallest step,
   keep the right hand in one register band (top note C4–G5), and move the bass to the
   nearest octave (E1–D3). A measured register is only a soft preference; smoothness wins.
Falls back to the default voicing when the harmonic stems are too quiet.
"""
import json, subprocess, sys, os
import numpy as np, librosa

track, sdir, off, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
T = json.load(open(track, encoding='utf-8-sig')); T = T.get('data', T)
chords = T['chords']
here = os.path.dirname(os.path.abspath(__file__))
ctjs = os.path.join(here, 'chordtones.js')
syms = sorted({c['chord'] for c in chords if c.get('chord')} | {o['chord'] for c in chords for o in (c.get('options') or []) if o.get('chord')})
parsed = json.loads(subprocess.check_output(['node', '-e',
  f"const CT=require({json.dumps(ctjs)});const o={{}};for(const s of {json.dumps(syms)}){{o[s]={{p:CT.parse(s),d:CT.defaultVoicing(s)}}}};console.log(JSON.stringify(o))"]))

SR, HOP, LO, NB = 22050, 512, 24, 72          # CQT C1..B6
def load(n):
    p = os.path.join(sdir, n + '.wav')
    return librosa.load(p, sr=SR, mono=True)[0] if os.path.exists(p) else None
hs = [x for x in (load('piano'), load('guitar'), load('other')) if x is not None]
if not hs:
    raise SystemExit(f"measure_voicings: no guitar, piano or other stem in {sdir}; the voicings are measured from them")
harm = sum(hs)
bass = load('bass')
low = harm + (bass if bass is not None else 0)
C_h = np.abs(librosa.cqt(harm, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
C_l = np.abs(librosa.cqt(low, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB))
fr = lambda t: int(max(0, t) * SR / HOP)
glob = np.percentile(C_h.sum(0), 95)

def unpartial(x, lowx):   # remove overtones of lower notes so they don't read as chord tones
    y = x.copy(); src = np.maximum(lowx, x)
    for k in range(NB):
        for d, w in ((12, .5), (19, .35), (24, .25), (28, .15)):
            if k - d >= 0: y[k] = max(0.0, y[k] - w * src[k - d])
    return y
E = lambda arr, m: arr[m - LO] if LO <= m < LO + NB else 0.0

TOP_LO, TOP_HI = 60, 79      # right-hand top note band: C4..G5
BASS_LO, BASS_HI = 28, 50    # bass band: E1..D3
RH_FLOOR = 53                # right hand stays above F3

def measure(sym, t, t1, full=False):
    """-> dict(p, keep, top, bass) or None; top/bass are the measured MIDI notes (soft targets)."""
    p = (parsed.get(sym) or {}).get('p')
    if not p: return None
    d = dict(p=p, keep=list(p['pcs']), top=None, bass=None)
    a, b = fr(t + off), fr(min(t1, t + 3.0) + off)
    nf = C_h.shape[1]; a, b = min(a, nf), min(b, nf)
    if b <= a + 1: return d
    Eh = C_h[:, a:b].mean(1); El = C_l[:, a:b].mean(1); raw = float(Eh.sum())
    if not np.isfinite(raw) or raw < 0.08 * glob: return d
    Eh = unpartial(Eh, El)
    d['bass'] = max((m for m in range(BASS_LO, BASS_HI + 1) if m % 12 == p['bass']), key=lambda m: E(El, m))
    rng = range(53, 89)
    pcE = {pc: max(E(Eh, m) for m in rng if m % 12 == pc) for pc in p['pcs']}
    mx = max(pcE.values()) or 1
    keep = [pc for pc in p['pcs'] if pcE[pc] >= 0.25 * mx]
    if len(keep) < 2: keep = sorted(p['pcs'], key=lambda pc: -pcE[pc])[:3]
    for pc in sorted(p['pcs'], key=lambda pc: -pcE[pc]):   # at least 3 right-hand pitch classes
        if len(keep) >= 3: break
        if pc not in keep: keep.append(pc)
    if not full: d['keep'] = keep
    cands = [m for m in rng if m % 12 in d['keep']]
    cm = max(E(Eh, m) for m in cands)
    d['top'] = max(m for m in cands if E(Eh, m) >= 0.4 * cm)
    return d

def rh_candidates(d):
    """All close-ish right-hand voicings of the kept pitch classes with the top note in the band."""
    pcs = d['keep']; out = []
    for top in range(TOP_LO, TOP_HI + 1):
        if top % 12 not in pcs: continue
        others = [pc for pc in pcs if pc != top % 12]
        notes = [top]
        for pc in others:   # nearest instance below the top note, within an octave, above the floor
            below = [m for m in range(max(RH_FLOOR, top - 12), top) if m % 12 == pc]
            if below: notes.append(max(below))
        if len(set(n % 12 for n in notes)) >= min(3, len(pcs)):
            out.append(tuple(sorted(set(notes))))
    return out or [tuple(sorted(set(parsed_default_rh(d))))]

def parsed_default_rh(d):
    return [57 + ((pc - 57) % 12 + 12) % 12 for pc in d['keep']]

def bass_candidates(d):
    return [m for m in range(BASS_LO, BASS_HI + 1) if m % 12 == d['p']['bass']]

def move(a, b):
    """Voice-leading distance between two right hands: each note to its nearest partner, both ways."""
    return (sum(min(abs(x - y) for y in b) for x in a) + sum(min(abs(x - y) for x in a) for y in b)) / 2

def local(d, rh, bm):
    c = 0.0
    if d['top'] is not None: c += 0.15 * abs(rh[-1] - min(max(d['top'], TOP_LO), TOP_HI))
    if d['bass'] is not None: c += 0.1 * abs(bm - d['bass'])
    c += 0.2 * abs((rh[0] + rh[-1]) / 2 - 67)          # gentle pull to the middle of the band
    c += 2.0 * sum(1 for x, y in zip(rh, rh[1:]) if y - x == 1)   # avoid muddy semitone clusters
    return c

def trans(r1, b1, r2, b2):
    return move(r1, r2) + 0.5 * abs(b1 - b2) + (3.0 if abs(r1[-1] - r2[-1]) > 5 else 0.0)

# ---- measure every chord, then choose all voicings together (Viterbi) ----
info = []
for i, c in enumerate(chords):
    t1 = chords[i+1]['t'] if i + 1 < len(chords) else T['duration']
    info.append(measure(c['chord'], c['t'], t1))
states = [[(rh, bm) for rh in rh_candidates(d) for bm in bass_candidates(d)] if d else [None] for d in info]
cost = [[local(info[0], *s) if s else 0.0 for s in states[0]]]; back = [[None] * len(states[0])]
for i in range(1, len(states)):
    ci, bi = [], []
    for s in states[i]:
        best, arg = 1e18, 0
        for j, s0 in enumerate(states[i-1]):
            tc = trans(s0[0], s0[1], s[0], s[1]) if (s and s0) else 0.0
            v = cost[i-1][j] + tc
            if v < best: best, arg = v, j
        ci.append(best + (local(info[i], *s) if s else 0.0)); bi.append(arg)
    cost.append(ci); back.append(bi)
k = int(np.argmin(cost[-1])); path = [0] * len(states)
for i in range(len(states) - 1, -1, -1):
    path[i] = k; k = back[i][k] if back[i][k] is not None else 0

res = []
for i, c in enumerate(chords):
    s = states[i][path[i]]; d = info[i]
    r = {'t': c['t'], 'chord': c['chord'], 'v': ([s[1]] + list(s[0])) if s else None,
         'src': 'measured' if (d and d['top'] is not None) else 'default'}
    if c.get('options'):   # option cards: every option voiced closest to the chosen previous voicing
        prev = states[i-1][path[i-1]] if i and states[i-1][path[i-1]] else s
        r['opts'] = {}
        for o in c['options']:
            t1 = chords[i+1]['t'] if i + 1 < len(chords) else T['duration']
            od = measure(o['chord'], c['t'], t1, full=True)
            if not od: r['opts'][o['chord']] = None; continue
            best = min(((rh, bm) for rh in rh_candidates(od) for bm in bass_candidates(od)),
                       key=lambda x: (trans(prev[0], prev[1], *x) if prev else 0) + local(od, *x))
            r['opts'][o['chord']] = [best[1]] + list(best[0])
    res.append(r)

json.dump({'voicings': res, 'method': 'chart chord tones; voiced tones and register measured from piano+guitar+other stems (CQT), bass octave from bass+harmonic stems; then smooth voice leading across the song (Viterbi: common tones kept, smallest moves, top note C4–G5, bass E1–D3)'}, open(out, 'w'))
N = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B']
nm = lambda m: N[m % 12] + str(m // 12 - 1)
tops = [r['v'][-1] for r in res if r['v']]
print(f"top-note moves: mean {np.mean(np.abs(np.diff(tops))):.1f} st, max {np.max(np.abs(np.diff(tops)))} st")
for r in res:
    print(f"{r['t']:7.2f} {str(r['chord'] or '?'):10s} {r.get('src','-'):8s} {' '.join(nm(m) for m in r['v']) if r['v'] else '-'}")
