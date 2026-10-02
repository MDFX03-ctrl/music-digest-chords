# Music Digest Chords

A local toolbox for a music producer. Separate a song, measure the beat, name the chords from the bass, and listen to it in one page. No API.

This one folder is the whole pack. An agent should read `AGENTS.md` first: it has the download links, the install commands, and the order of use. This README follows the same steps.

The rules for naming chords are in `prompts/chord-naming.md`. That is the naming spec, not the install guide.

## Download these yourself

None of these are in the pack. Install them and put them on `PATH`; the code calls `python`, `node`, and `ffmpeg` by name only.

| Need | Where | How |
|---|---|---|
| Python 3.11 | https://www.python.org/downloads/release/python-3119/ | On Windows use `python-3.11.9-amd64.exe` and check "Add python.exe to PATH". |
| Node.js, current LTS | https://nodejs.org/en/download | Used only to run `tools/chordtones.js`. No `npm install`. |
| ffmpeg | https://ffmpeg.org/download.html | Windows builds are at https://www.gyan.dev/ffmpeg/builds/ (get `ffmpeg-release-essentials.zip`); add its `bin` folder to `PATH`. |
| PyTorch CPU | https://download.pytorch.org/whl/cpu | Use the command below. Do not install the default CUDA wheel. |
| Demucs | https://github.com/adefossez/demucs | `pip install demucs`. The first separation downloads `htdemucs_6s` (about 52 MB) from https://huggingface.co/adefossez/HTDemucs-6s into the Hugging Face cache. No account needed. |

## Install

Run these from this directory, with the Python 3.11 above. Do not create a virtualenv on a data drive.

```
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt demucs
python -m mdchord doctor
```

`requirements.txt` is only numpy, soundfile, librosa, and pedalboard. `doctor` must show `ffmpeg` and `node` found, and all four packages plus demucs importable. `MDCHORD_API_KEY` stays empty.

## Listen to the demo first

```
python -m mdchord demo
python -m mdchord serve
```

Open the address the terminal prints; the default is `http://127.0.0.1:8765/`. The page is Chord Follower. Stop it with Ctrl+C. Do not leave it running.

The demo is an 8 second loop: C, G, Am, F. Picks are written to `picks.json` and do not change the chord names.

One piano ships in the pack: Salamander Grand Piano, a sampled one by Alexander Holm, CC BY 3.0. Keep the credit line in the page footer. It is the default and the only instrument. The other one, Aurora Grand, is a modelled piano that links JUCE, so it is not distributed here; `THIRD-PARTY.md` says where its source lives. Do not put a VST3 in the pack.

## The song folder

New songs go under `songs\`, one folder per song, with an ASCII name such as `songs\folder`. Once a folder has `track.json`, a bare `python -m mdchord serve` lists it. `songs\libraries.txt` can name more song folders, one path per line; a line starting with `#` is skipped. To open just one song, `python -m mdchord serve songs\folder` still works and ignores that file. A song added while the server is running shows up on reload.

On Windows, double-click `start-follower.bat` in the project folder. It serves this library and opens the browser. Close that window to stop. Do not leave it running.

On the page the only song control is Remove. It asks once, then deletes that song's folder, including a song that came from a folder named in `libraries.txt`. It does not delete a library folder and it does not rewrite `track.json`.

## Analyse a song you have the right to use

```
python -m mdchord digest "AUDIO" --measure-only --out songs\FOLDER --title "TITLE" --artist "ARTIST"
```

This step writes only `stems`, `input.wav`, `manifest.json`, `grid.json`, `bars.json`, and `measurement.json`. It does not name chords. The first run of Demucs is the slow step.

Then, in this order:

1. Read `manifest.json`, `grid.json`, `bars.json`, and `prompts/chord-naming.md`.
2. `change_counts` tells you which beat the bass changes chord on. If the peak is not beat 1, remeasure once with the downbeat shifted, or raise `--split`. Do not remeasure in a loop.
3. Write `track.json` yourself. Bass first; when the bass is under about −60 dB, use the lowest harmonic note. Use a chart only when the user supplied one verbatim. Chroma only checks quality (major or minor, sus, a drone). Do not name a chord from chroma alone. With no chart you must not mark `conf` as `ok`. `verified` stays false until the listener accepts the names.
4. For an uncertain chord, score 2 or 3 options. The first option is the current guess. Do not write `N.C.` in the JSON; the page adds it.

```
python tools/chord_options.py songs\FOLDER\track.json songs\FOLDER\stems 0 INDEX
python tools/measure_voicings.py songs\FOLDER\track.json songs\FOLDER\stems 0 songs\FOLDER\voicings.json
```

5. Write `analysis.md` in that folder and say there is no ear check yet.
6. `python -m mdchord serve` opens every finished song under `songs\`. Give the user the command and the URL. When stems exist, Full mix starts muted.

Do not run `digest` without `--measure-only`. That older path calls an API and will refuse to start when the key is missing.

Do not search the web for a chart of the user's own song.

A song can live anywhere. To have one show up in the one-click library, write its folder path on a line in `songs\libraries.txt` (one per line; a `#` line is skipped); every direct child with `track.json` counts as one song. `libraries.txt` belongs to this machine only and is listed in `.gitignore`; do not write the paths in it into a hand-out.

## Check it works

```
python -m unittest discover -s tests
```

That runs the full suite (Unittest, not pytest, so there is nothing extra to install). `python -m mdchord doctor` re-checks the local tools and packages.

## Do not ship or commit

Audio under `songs\`, `.env`, `instruments.json`, and any wav, mp3, mp4, or flac. `songs\README.md` can ship. Do not put a machine path into a hand-out. Finished songs stay on the machine that made them.
