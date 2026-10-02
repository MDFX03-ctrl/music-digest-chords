# Assets and third-party notices

The code in this repository is offered under the MIT licence in `LICENSE`, and
everything that ships here is compatible with it. The modelled piano is
deliberately not shipped: see "Aurora Grand" below.

One audio asset ships inside this pack. It is listed here so that anyone who
clones the repository knows what the binary file is and what terms apply.

## Bundled instrument

| Path | Size | What it is | Terms |
|---|---|---|---|
| `instruments/salamander.m4a` + `instruments/salamander.json` | ~4 MB | Sample bank for the piano, one sample every minor third from A0 to C8. The default and only instrument here. | Salamander Grand Piano by **Alexander Holm**, **CC BY 3.0**. |

### Salamander Grand Piano — attribution

Required by CC BY 3.0, and it must stay visible:

- Original source: https://sfzinstruments.github.io/pianos/salamander/
- Author: Alexander Holm
- The audio in `instruments/salamander.m4a` is the Tone.js Salamander set
  (single velocity layer, Yamaha C5), taken via
  https://tonejs.github.io/audio/salamander/ and recorded in
  `instruments/salamander.json` as `samplesFrom`.
- License: Creative Commons Attribution 3.0 Unported (CC BY 3.0)
  https://creativecommons.org/licenses/by/3.0/
- This file is an adaptation of that set: the samples were re-encoded to AAC
  and joined into one file, and each sample's offset and length is recorded in
  `instruments/salamander.json`. CC BY 3.0 asks for that change to be stated,
  so it is stated here and in the page footer.
- The credit line is the page footer of `viewer/index.html`, under the chord
  chart, so it stays visible whatever the track lanes are doing.

If you redistribute this pack, or a work built on it, keep that credit line.

`salamander.json` records the sample layout (offsets, durations, MIDI notes). It
is generated from the same source and carries the same license.

### Aurora Grand

A physically modelled grand piano: VST3, AU, LV2 and standalone, with no
samples. Its source lives in a separate repository,
<https://github.com/MDFX03-ctrl/acoustic-piano-claude-cloud>, whose own README
says:

> The engine in `src/dsp`, the tools and the tests are original code. The
> plugin links against JUCE, which is available under the GPLv3 or a
> commercial licence from the JUCE developers; distribute the plugin under
> terms compatible with the JUCE licence you hold.

JUCE is dual licensed: GPLv3, or a commercial licence bought from the JUCE
developers. The project pins JUCE 8.0.9 in `cmake/FetchJUCE.cmake`.

**Aurora Grand does not ship with this repository.** A JUCE-linked binary
cannot be redistributed under this repository's MIT licence, so it is not part
of the pack at all. The page is unaffected: the sampled bank above is the
default and only instrument, so chord playback works with nothing else
installed.

If you want the modelled piano anyway, build it from the repository above and
add the result to `instruments/Aurora Grand.vst3/`. `mdchord/vst.py` will pick
it up and offer it alongside the sampled bank. That binary is then yours to
license, not this repository's: if you distribute it, do so from its own
repository under terms compatible with the JUCE licence you hold, not from here.

`instruments.json` is a local catalog that `mdchord/vst.py` writes when you add
a plugin through the page. It is gitignored and not part of the pack.

## Fonts loaded by the page

`viewer/index.html` loads three families from Google Fonts:

- Instrument Serif
- IBM Plex Sans
- IBM Plex Mono

All three are licensed under the SIL Open Font License 1.1. They are fetched
from `fonts.googleapis.com` at page load, which means the page is not strictly
offline when it is open. If that matters, the stylesheet link can be removed:
the page falls back to system fonts and nothing else changes.

## Python and other dependencies

Installed by the user, not vendored here. See `requirements.txt` for the list of
minimum versions, and `AGENTS.md` for the CPU-only PyTorch and Demucs install commands.
Demucs downloads its model weights (about 52 MB) from Hugging Face on first use.
Those weights are not part of this repository.

## Song audio

No song audio belongs in this repository. `songs/*` is gitignored apart from
`songs/README.md`, and `songs/libraries.txt` stays on the machine that made it.
