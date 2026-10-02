#!/usr/bin/env python3
"""Music Digest: turn a composed score into a MIDI file, rendered piano stems and Chord Follower docs.

Usage: python3 score_to_daw.py <score.json> <salamander.wav> <instrument.json> <out dir> [--slug my-piece]

score.json (written by a piece script, e.g. compositions/<piece>.py):
  {title, artist, key, bpm, beatsPerBar, lead (s of silence before beat 0), tail (s after the end),
   notes: [{t, d, m, v, part}]   t/d in beats from beat 0, m = MIDI pitch, v = velocity, part = key of `parts`
   chords: [{t, chord, roman}]   t in beats;  sections: [{name, start, end}] in beats
   voicings: [{t, chord, v:[bass, ...]}]      optional explicit voice-led voicings (stable-voicing rule)
   parts: {part: "Lane name"}}   first part = melody (goes to the Melody lane too)
   meter: [{t, num}]             optional time-signature changes in beats (e.g. 2/4 stop bar, then back to 4)
   keys: [{t, key}]              optional key changes in beats ('Eb major', 'E major', 'A minor'); MIDI key signatures + DAW key lane
   kinds: {part: stem kind}      optional Chord Follower lane kinds (vocals, drums, bass, guitar, piano, other)
salamander.wav  : the Chord Follower piano sprite decoded to WAV (Artifact read of instruments/piano `asset`, then
                  ffmpeg -i <id>.mp4 -ac 1 -ar 44100 sal.wav);  instrument.json = the instruments/piano doc.

Writes to <out dir>: <slug>.mid (type 1: tempo track + one track per part, sustain via note lengths),
  stems/<part>.wav + daw/<part>.mp4 (Salamander render, per part, same reverb, sample-aligned),
  mix.wav, track.json (Chord Follower track doc without `stems` ids), melody.json (parts/melody), piano.json (parts/piano).
Times in the docs are seconds on the render's timeline (offset 0); barStart = lead.
Then: upload daw/*.mp4 with Artifact (asset: true), add {id, kind, name, offset: 0} to track.json `stems`, write the docs.
"""
import argparse, json, os, subprocess
import numpy as np, soundfile as sf
from scipy.signal import butter, lfilter, fftconvolve

ap = argparse.ArgumentParser()
ap.add_argument('score'); ap.add_argument('sprite'); ap.add_argument('instrument'); ap.add_argument('out')
ap.add_argument('--slug', default=None); ap.add_argument('--reverb', type=float, default=0.22)
a = ap.parse_args()
S = json.load(open(a.score)); I = json.load(open(a.instrument)); I = I.get('data', I)
slug = a.slug or S['title'].lower().replace(' ', '-')
os.makedirs(os.path.join(a.out, 'stems'), exist_ok=True); os.makedirs(os.path.join(a.out, 'daw'), exist_ok=True)
bpm = S['bpm']; B = 60 / bpm; lead = S.get('lead', 0.5); tail = S.get('tail', 4.0)
sec = lambda beats: lead + beats * B
parts = list(S['parts'].keys())

# ---------- MIDI (type 1, 480 ppq) ----------
import mido
ppq = 480; mf = mido.MidiFile(type=1, ticks_per_beat=ppq)
t0 = mido.MidiTrack(); mf.tracks.append(t0)
t0.append(mido.MetaMessage('track_name', name=S['title'], time=0))
t0.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(bpm), time=0))
# time signatures: score `meter` = [{t (beats), num}] for odd bars (e.g. a 2/4 stop bar and the return to 4/4)
last = 0
for mt in [{'t': 0, 'num': S.get('beatsPerBar', 4)}] + sorted(S.get('meter', []), key=lambda x: x['t']):
    tick = round(mt['t'] * ppq)
    t0.append(mido.MetaMessage('time_signature', numerator=mt['num'], denominator=4, time=tick - last)); last = tick
KS = {'Eb major': 'Eb', 'E major': 'E', 'D major': 'D', 'C major': 'C', 'F major': 'F', 'G major': 'G', 'A major': 'A', 'Bb major': 'Bb',
      'Ab major': 'Ab', 'Db major': 'Db', 'B major': 'B', 'F# major': 'F#', 'A minor': 'Am', 'E minor': 'Em', 'D minor': 'Dm', 'C minor': 'Cm'}
last = 0; t0b = mido.MidiTrack(); mf.tracks.append(t0b)
for kk in (S.get('keys') or [{'t': 0, 'key': S['key']}]):
    if kk['key'] in KS:
        tick = round(kk['t'] * ppq); t0b.append(mido.MetaMessage('key_signature', key=KS[kk['key']], time=tick - last)); last = tick
for ci, part in enumerate(parts):
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage('track_name', name=S['parts'][part], time=0))
    tr.append(mido.Message('program_change', program=0, channel=ci, time=0))
    ev = []
    for n in S['notes']:
        if n['part'] != part: continue
        ev.append((round(n['t'] * ppq), 1, n['m'], n['v'])); ev.append((round((n['t'] + n['d']) * ppq) - 1, 0, n['m'], 0))
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick, on, m, v in ev:
        tr.append(mido.Message('note_on' if on else 'note_off', note=m, velocity=v if on else 0, channel=ci, time=tick - last)); last = tick
mid = os.path.join(a.out, slug + '.mid'); mf.save(mid)

# ---------- render with the Salamander sprite ----------
SR = 44100
spr, sr0 = sf.read(a.sprite); assert sr0 == SR
if spr.ndim > 1: spr = spr.mean(1)
samples = I['samples']
dur_total = sec(max(n['t'] + n['d'] for n in S['notes'])) + tail
N = int(dur_total * SR)
cache = {}
def voice(m, length, vel):
    s = min(samples, key=lambda x: abs(x['midi'] - m))
    rate = 2 ** ((m - s['midi']) / 12)
    a0 = int(s['start'] * SR); src = spr[a0:a0 + int(s['dur'] * SR)]
    n = int(min(length + 0.35, len(src) / rate / SR) * SR)
    idx = np.arange(n) * rate
    y = np.interp(idx, np.arange(len(src)), src)
    rel = int(0.3 * SR); keep = int(length * SR)
    if keep < n:  # damper release after the note (or pedal) ends
        env = np.ones(n); env[keep:] = np.exp(-np.arange(n - keep) / (0.08 * SR)); y = y * env
    y[-256:] *= np.linspace(1, 0, min(256, len(y)))
    g = (vel / 127) ** 1.7
    fc = 1800 + 9000 * (vel / 127) ** 2          # softer notes are darker (single velocity layer)
    key = round(fc, -2)
    if key not in cache: cache[key] = butter(1, key / (SR / 2))
    b, aa = cache[key]
    return g * lfilter(b, aa, y)
dry = {p: np.zeros(N) for p in parts}
for n in S['notes']:
    y = voice(n['m'], n['d'] * B, n['v']); i0 = int(sec(n['t']) * SR)
    seg = dry[n['part']][i0:i0 + len(y)]; seg += y[:len(seg)]
# stereo room reverb (synthetic IR, same for every part so stems sum to the mix)
rng = np.random.default_rng(1); L = int(2.4 * SR); tt = np.arange(L) / SR
ir = [rng.standard_normal(L) * np.exp(-tt / 0.55) for _ in range(2)]
b, aa = butter(1, 5000 / (SR / 2)); ir = [lfilter(b, aa, x) for x in ir]; ir = [x / np.sqrt(np.sum(x ** 2)) for x in ir]
wet = {}
peak = max(np.max(np.abs(sum(dry.values()))), 1e-9)
out = {}
for p in parts:
    x = dry[p] / peak * 0.5
    st = np.stack([x * (1 - a.reverb) + a.reverb * fftconvolve(x, ir[c])[:N] * 2.2 for c in range(2)], 1)
    out[p] = st
mix = sum(out.values()); pk = np.max(np.abs(mix)); gain = 0.89 / pk
man = []
for p in parts:
    w = os.path.join(a.out, 'stems', p + '.wav'); sf.write(w, out[p] * gain, SR)
    m4 = os.path.join(a.out, 'daw', p + '.mp4')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', w, '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', m4], check=True)
    man.append({'part': p, 'name': S['parts'][p], 'kind': (S.get('kinds') or {}).get(p, 'piano'), 'file': m4})
sf.write(os.path.join(a.out, 'mix.wav'), mix * gain, SR)

# ---------- Chord Follower docs ----------
mono = (mix * gain).mean(1); hop = SR // 10
rms = np.sqrt(np.convolve(mono ** 2, np.ones(hop) / hop, 'same')[::hop])
env = [int(np.clip((20 * np.log10(r + 1e-9) + 45) / 45 * 100, 0, 100)) for r in rms]
chords = [{'t': round(sec(c['t']), 3), 'chord': c['chord'], 'roman': c['roman']} for c in S['chords']]
starts = [round(sec(s['start']), 3) for s in S['sections']]
def row_start(tb):   # new chart row at each section start and every 2 bars inside a section
    s0 = max((x['start'] for x in S['sections'] if x['start'] <= tb + 1e-6), default=0)
    return abs(((tb - s0) % 8)) < 1e-6
rowBreaks = [i for i, c in enumerate(S['chords']) if i and row_start(c['t'])]
track = {'title': S['title'], 'artist': S['artist'], 'key': S['key'], 'bpm': bpm, 'beatsPerBar': S.get('beatsPerBar', 4),
         'barStart': lead, 'duration': round(N / SR, 2), 'keys': [{'t': round(sec(kk['t']), 3) if kk['t'] else 0, 'key': kk['key']} for kk in (S.get('keys') or [{'t': 0, 'key': S['key']}])],
         'sections': [{'name': s['name'], 'start': round(sec(s['start']), 3) if s['start'] else 0, 'end': round(sec(s['end']), 3)} for s in S['sections']],
         'chords': chords, 'rowBreaks': rowBreaks, 'env': env, 'envRate': 10, 'audios': [], 'stems': [],
         'stemsFrom': 'Rendered from the MIDI with the Salamander Grand Piano sprite (score_to_daw.py)'}
json.dump(track, open(os.path.join(a.out, 'track.json'), 'w'), ensure_ascii=False)
mp = parts[0]; mn = []
for n in sorted((n for n in S['notes'] if n['part'] == mp), key=lambda n: n['t']):
    mn += [round(sec(n['t']) * 100), round(n['d'] * B * 100), n['m']]
json.dump({'name': S['parts'][mp], 'timeDiv': 100, 'notes': mn}, open(os.path.join(a.out, 'melody.json'), 'w'), ensure_ascii=False)
if S.get('voicings'):
    json.dump({'voicings': [{'t': round(sec(v['t']), 3), 'chord': v['chord'], 'v': v['v'], 'src': 'score'} for v in S['voicings']],
               'method': 'explicit voicings from the score (the accompaniment itself)', 'source': 'score_to_daw.py'},
              open(os.path.join(a.out, 'piano.json'), 'w'), ensure_ascii=False)
json.dump({'midi': mid, 'stems': man, 'duration': round(N / SR, 2)}, open(os.path.join(a.out, 'manifest.json'), 'w'), indent=1)
print(json.dumps({'midi': mid, 'stems': man, 'duration': round(N / SR, 2), 'chords': len(chords), 'rows': len(rowBreaks)}, indent=1))
