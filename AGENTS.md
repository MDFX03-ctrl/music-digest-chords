# Music Digest Chords

Local toolbox for a music producer. Separate a song, measure the bass, name the chords, and listen in one page. No API key. Do not call a model endpoint, and do not add one.

Run every command from this directory. Python 3.11. Do not create a virtualenv on a data drive.

`prompts/chord-naming.md` is the naming spec. Follow it when you write chords. It is not the install guide, and it is not a reason to answer in JSON only when the user asked you to install or listen.

## Download

Install these yourself. This pack does not contain them. Put each program on `PATH`. Look them up by name (`ffmpeg`, `node`, `python`). Do not write a machine path into the repo.

| Need | Where | How |
|---|---|---|
| Python 3.11 | https://www.python.org/downloads/release/python-3119/ | Windows: `python-3.11.9-amd64.exe`. Check "Add python.exe to PATH". |
| Node.js, current LTS | https://nodejs.org/en/download | Used only to run `tools/chordtones.js`. No `npm install`. |
| ffmpeg | https://ffmpeg.org/download.html | Windows builds: https://www.gyan.dev/ffmpeg/builds/ (`ffmpeg-release-essentials.zip`). Add its `bin` folder to `PATH`. |
| PyTorch CPU | https://download.pytorch.org/whl/cpu | Command below. Do not install the default CUDA wheel. |
| Demucs | https://github.com/adefossez/demucs | `pip install demucs`. The first separation downloads `htdemucs_6s` (about 52 MB) from https://huggingface.co/adefossez/HTDemucs-6s into the Hugging Face cache. No account and no token. |

## Install

```
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt demucs
python -m mdchord doctor
```

`requirements.txt` is only numpy, soundfile, librosa, pedalboard, and mido (pedalboard needs it to play MIDI and does not install it). `torch` and `demucs` stay out of that file.

`doctor` must show `ffmpeg` and `node` found, and numpy, soundfile, librosa, demucs, pedalboard, mido importable. There is no API key to set. This pack never calls a model endpoint, and no code path can.

## Listen to the demo

```
python -m mdchord demo
python -m mdchord serve
```

Open the URL it prints. Default is `http://127.0.0.1:8765/`. The page is Chord Follower. Stop the server with Ctrl+C. Do not leave it running.

The demo is an 8 second loop: C, G, Am, F. Picks go to `picks.json` and do not change `track.json`.

A piano is included: Salamander Grand Piano, a sampled one by Alexander Holm, CC BY 3.0. It is the default and only instrument. Credit stays in the page footer. Aurora Grand, the modelled piano, is not shipped here: it links JUCE, and `THIRD-PARTY.md` says where its source is. Do not add a VST3 to the pack.

## Song library

`songs/` is where each new song is saved. One folder per song, for example `songs/FOLDER`. The folder name is ASCII. `python -m mdchord serve` with no path lists every direct child that has `track.json`. `songs/libraries.txt`, when present, adds other library folders, one path per line. A `#` line is skipped. `python -m mdchord serve songs/FOLDER` still opens one song and ignores that file. A song added while the server is running shows up on reload.

On Windows, double-click `start-follower.bat`. It serves this library and opens the browser. Close that window to stop. Do not leave it running.

On the page, the only song control is Remove. It asks once, then deletes that song folder, including a song that came from a folder named in `libraries.txt`. It does not delete a library folder and it does not rewrite `track.json`.

`songs/README.md` explains the same thing. Song audio stays out of a hand-out copy.

## One song the user may use

```
python -m mdchord digest "AUDIO" --out songs/FOLDER --title "TITLE" --artist "ARTIST"
```

It writes `stems/*.wav`, `input.wav`, `manifest.json`, `grid.json`, `bars.json`, and `measurement.json`. It does not name chords, and it cannot: `digest` only measures. The first run of Demucs is the slow step.

Then:

1. Read `manifest.json`, `grid.json`, `bars.json`, and `prompts/chord-naming.md`.
2. `grid.json` `change_counts[i]` is how often the bass pitch changes on beat `i` mod 4. If the peak is not index 0, remeasure once with `--bar-start` set to `beat_phase + k * period`, or raise `--split` when changes fall inside the half bar. Do not loop.
3. Write `track.json`. Bass pitch first. If the bass is under about −60 dB, use the lowest harmonic note. A verbatim chart the user supplied comes next. Chroma only checks quality (minor, sus, a drone). Do not name a chord from chroma alone. No chart and no confident bass: leave the chord null or `N.C.`, `conf` `"low"`. Never set `conf` `"ok"` without a chart whose bass matches. `verified` stays false until the user accepts the names.
4. Uncertain chords: score 2 or 3 symbols. `--save` records the scores in `measurement.json` as `candidates`, and `check` accepts only options scored at that chord's time. The first option is the current chord. Do not put `N.C.` in the JSON. The page adds it.

```
python tools/chord_options.py songs/FOLDER/track.json songs/FOLDER/stems 0 INDEX --save songs/FOLDER/measurement.json
python tools/score_candidates.py songs/FOLDER/track.json songs/FOLDER/stems 0 "{\"INDEX\":[\"A\",\"Am\"]}" --save songs/FOLDER/measurement.json
```

5. Voice the chords. Stem offset is 0 when stems were made by this tool.

```
python tools/measure_voicings.py songs/FOLDER/track.json songs/FOLDER/stems 0 songs/FOLDER/voicings.json
```

6. Validate what you wrote. Fix every reported problem before handing the song over.

```
python -m mdchord check songs/FOLDER
```

7. Write `analysis.md` in that folder. Say there is no ear check yet.

```
python -m mdchord serve
```

`serve` with no path opens every song in `songs/`, plus folders named in `songs/libraries.txt`. On Windows, `start-follower.bat` does that and opens the browser. Give the user the command and the URL. When stems exist, Full mix starts muted. Do not claim you clicked Play.

There is no API path and no `--measure-only` flag: measuring is all `digest` does.

## Do not ship or commit

Song audio under `songs/`, `songs/libraries.txt`, `.env`, `instruments.json`, and any wav, mp3, mp4, or flac. `songs/README.md` can ship. Do not put a machine path into the hand-out. Finished songs stay on the machine that made them. Do not init a git repo or upload unless the user asks. Do not set `GROK_HOME`. Do not turn this folder into a plugin. Do not search for a chart of the user's own song.
