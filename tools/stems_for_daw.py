#!/usr/bin/env python3
"""Music Digest: split a song into 6 stems for the Chord Follower DAW.

Usage:  python3 stems_for_daw.py <input audio> <out dir> [--model htdemucs_6s] [--kbps 160]

Output in <out dir>:
  stems/<stem>.wav        full-quality stems (for chord/melody measurement)
  daw/<stem>.mp4          AAC-in-MP4 files to upload as Chord Follower assets
  manifest.json           per-stem level (dBFS RMS), share of energy, duration

Stems are sample-aligned with the input, so every stem uses the same `offset`
(input time - chord-timeline time) as the audio it was separated from.
Setup (once, from the project directory, Python 3.11):
  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
  pip install -r requirements.txt demucs
"""
import argparse, json, os, subprocess, sys
import numpy as np, soundfile as sf

ORDER = ["vocals", "drums", "bass", "guitar", "piano", "other"]

def run(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--model", default="htdemucs_6s")
    ap.add_argument("--kbps", type=int, default=160)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    wav = os.path.join(a.out, "input.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.src, "-vn", "-ac", "2", "-ar", "44100", wav])
    run([sys.executable, "-m", "demucs", "-n", a.model, "-o", os.path.join(a.out, "sep"), wav])
    sepdir = os.path.join(a.out, "sep", a.model, "input")
    os.makedirs(os.path.join(a.out, "stems"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "daw"), exist_ok=True)
    stems, energies = [], {}
    names = [n for n in ORDER if os.path.exists(os.path.join(sepdir, n + ".wav"))]
    for n in names:
        x, sr = sf.read(os.path.join(sepdir, n + ".wav"))
        energies[n] = float(np.mean(x ** 2))
        os.replace(os.path.join(sepdir, n + ".wav"), os.path.join(a.out, "stems", n + ".wav"))
    total = sum(energies.values()) or 1.0
    for n in names:
        src = os.path.join(a.out, "stems", n + ".wav"); dst = os.path.join(a.out, "daw", n + ".mp4")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c:a", "aac", "-b:a", f"{a.kbps}k", "-movflags", "+faststart", dst])
        x, sr = sf.read(src)
        stems.append({
            "kind": n, "file": dst, "bytes": os.path.getsize(dst),
            "rms_db": round(10 * np.log10(energies[n] + 1e-12), 1),
            "share": round(energies[n] / total, 3),
            "duration": round(len(x) / sr, 2),
        })
    man = {"source": a.src, "model": a.model, "stems": stems}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=2)
    print(json.dumps(man, indent=2))

if __name__ == "__main__":
    main()
