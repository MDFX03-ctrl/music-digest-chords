# songs

One folder per song. A new digest goes here:

```
python -m mdchord digest "AUDIO" --out songs/FOLDER --title "TITLE" --artist "ARTIST"
```

That measures the song and writes no chord names. You name them into `track.json` following `prompts/chord-naming.md`, then run `python -m mdchord check songs/FOLDER` to validate it.

Pick an ASCII folder name. The page lists it once that folder has `track.json`. `python -m mdchord demo` writes `songs/demo`.

Open every song in this folder:

```
python -m mdchord serve
```

On Windows, double-click `start-follower.bat` in the project folder. It starts that same library and opens the browser. Close the server window to stop.

`libraries.txt` in this folder can name more library folders, one path per line. A line starting with `#` is skipped. Each direct child with `track.json` is included. That file stays on this machine.

Reload the page after adding a song. Remove asks once, then deletes that song folder. It does not delete this library and it does not rewrite `track.json`.

Song audio here stays on this machine. This README is the only file from `songs/` that belongs in a hand-out copy.
