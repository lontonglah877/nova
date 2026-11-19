#!/usr/bin/env python3
"""NOVA - entry point untuk panel Botkeep (runtime Python).

Alur: baca server.env -> siapkan venv -> install Hermes -> tulis config
-> jalankan gateway di foreground. Idempoten: aman dijalankan ulang.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
HOME = ROOT / "hermes-home"
VENV = ROOT / ".venv"
STAMP = ROOT / ".deps-ok"
ENVFILE = ROOT / "server.env"
PY = sys.executable


def log(msg: str) -> None:
    print("[nova] " + str(msg), flush=True)


def run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    kw.setdefault("cwd", str(ROOT))
    return subprocess.run([str(c) for c in cmd], **kw)


def load_env() -> dict:
    env = {}
    if ENVFILE.exists():
        for raw in ENVFILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def report() -> None:
    log("python " + sys.version.split()[0] + " @ " + sys.executable)
    log("cwd " + str(ROOT))
    try:
        mem = pathlib.Path("/proc/meminfo").read_text()
        for line in mem.splitlines():
            if line.startswith(("MemTotal", "MemAvailable")):
                log(line.strip())
    except Exception:
        pass
    try:
        du = shutil.disk_usage(str(ROOT))
        log(f"disk free {du.free / 1048576:.0f} MB / total {du.total / 1048576:.0f} MB")
    except Exception:
        pass
    log(f"cpu_count {os.cpu_count()}")


def venv_python() -> pathlib.Path:
    cand = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return cand


def ensure_venv() -> pathlib.Path:
    vp = venv_python()
    if vp.exists():
        return vp
    log("membuat venv...")
    r = run([PY, "-m", "venv", str(VENV)])
    if r.returncode != 0 or not vp.exists():
        log("venv gagal, pakai python sistem + --target")
        return pathlib.Path(PY)
    return vp


def pip_install(vp: pathlib.Path) -> bool:
    req = ROOT / "requirements.txt"
    args = [str(vp), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "-r", str(req)]
    r = run(args)
    if r.returncode != 0:
        log("pip install gagal (exit %s)" % r.returncode)
        return False
    STAMP.write_text(str(int(time.time())), encoding="utf-8")
    return True


def write_config(env: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "skills").mkdir(exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)

    cfg = HOME / "config.yaml"
    if not cfg.exists():
        cfg.write_text(
            "model:\n"
            "  default: gemini-3-flash-preview\n"
            "  provider: custom\n"
            "  base_url: https://generativelanguage.googleapis.com/v1beta/openai/\n"
            "  api_mode: chat_completions\n"
            "  key_env: NOVA_GEMINI_KEY\n"
            "providers:\n"
            "  custom:\n"
            "    name: google-ai-studio\n"
            "    base_url: https://generativelanguage.googleapis.com/v1beta/openai/\n"
            "    model: gemini-3-flash-preview\n"
            "    key_env: NOVA_GEMINI_KEY\n"
            "agent:\n"
            "  max_turns: 200\n"
            "  reasoning_effort: medium\n"
            "terminal:\n"
            "  backend: local\n"
            "  timeout: 180\n"
            "memory:\n"
            "  memory_enabled: true\n"
            "  user_profile_enabled: true\n"
            "display:\n"
            "  compact: true\n",
            encoding="utf-8",
        )
        log("config.yaml ditulis")

    envfile = HOME / ".env"
    lines = []
    if envfile.exists():
        lines = [l for l in envfile.read_text(encoding="utf-8").splitlines() if not l.startswith("NOVA_GEMINI_KEY=")]
    key = env.get("NOVA_GEMINI_KEY", "")
    if key:
        lines.append("NOVA_GEMINI_KEY=" + key)
    envfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(envfile, 0o600) if os.name != "nt" else None
    log("hermes-home/.env diperbarui (kunci tidak dicetak)")

    src = ROOT / "skills" / "nova"
    dst = HOME / "skills" / "nova"
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        log("skill nova terpasang")


def main() -> int:
    report()
    env = load_env()
    vp = ensure_venv()

    if not STAMP.exists():
        if not pip_install(vp):
            log("berhenti: dependency belum siap")
            return 1
    else:
        log("dependency sudah terpasang (stamp)")

    write_config(env)

    child_env = dict(os.environ)
    child_env.update(env)
    child_env["HERMES_HOME"] = str(HOME)
    child_env["PYTHONUNBUFFERED"] = "1"
    venv_bin = str(vp.parent)
    child_env["PATH"] = venv_bin + os.pathsep + child_env.get("PATH", "")

    hermes = vp.parent / ("hermes.exe" if os.name == "nt" else "hermes")
    if not hermes.exists():
        hermes = vp.parent / "hermes"
    if not hermes.exists():
        log("binary hermes tidak ditemukan, coba modul python")
        cmd = [str(vp), "-c", "from hermes_cli.main import main; main()", "gateway", "run"]
    else:
        cmd = [str(hermes), "gateway", "run"]

    log("menjalankan gateway...")
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=child_env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
