#!/usr/bin/env python3
"""Entry point Botkeep: `python main.py`.

Botkeep menjalankan satu proses non-interaktif dari root repo. Semua kerja
nyata ada di server/boot.py (unduh sumber, venv, Hermes, Node, bridge,
config, lalu `hermes gateway run` di foreground).
"""
import pathlib
import runpy
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BOOT = ROOT / "server" / "boot.py"

if not BOOT.exists():
    print("[nova] server/boot.py tidak ditemukan", flush=True)
    sys.exit(2)

sys.argv = [str(BOOT)] + sys.argv[1:]
runpy.run_path(str(BOOT), run_name="__main__")
