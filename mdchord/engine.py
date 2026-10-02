"""Run the copied measurement scripts. No chord names are decided here."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


class Engine:
    def stems(self, src, out, model="htdemucs_6s"):
        run([sys.executable, str(TOOLS / "stems_for_daw.py"), str(src), str(out), "--model", model])

    def grid(self, stems, dest, bpm_min=60, bpm_max=140):
        run([
            sys.executable, str(TOOLS / "beat_grid.py"), str(stems),
            "--bpm-min", str(bpm_min), "--bpm-max", str(bpm_max),
            "--out", str(dest),
        ])

    def bars(self, stems, mix, bpm, start, dest, beats=4, split=2, shorts=()):
        cmd = [
            sys.executable, str(TOOLS / "bar_report.py"), str(stems), str(mix),
            str(bpm), str(start),
            "--beats", str(beats), "--split", str(split), "--out", str(dest),
        ]
        for item in shorts:
            cmd.extend(["--short", item])
        run(cmd)

    def options(self, track, stems, offset, indexes):
        if not indexes:
            return {}
        cmd = [
            sys.executable, str(TOOLS / "chord_options.py"), str(track), str(stems),
            str(offset), *[str(i) for i in indexes],
        ]
        print("+", " ".join(cmd), flush=True)
        out = subprocess.check_output(cmd, text=True)
        start, end = out.find("{"), out.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError("chord_options.py returned no JSON")
        return json.loads(out[start:end + 1])

    def voicings(self, track, stems, offset, dest):
        run([
            sys.executable, str(TOOLS / "measure_voicings.py"), str(track), str(stems),
            str(offset), str(dest),
        ])
