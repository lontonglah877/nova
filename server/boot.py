#!/usr/bin/env python3
"""NOVA server bootstrap - entry point Botkeep (Python 3.13).

1. unduh bundle NOVA bila belum ada
2. siapkan venv + Hermes
3. tulis config/skill/.env
4. jalankan gateway (foreground)
"""
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
HOME = ROOT / "hermes-home"
VENV = ROOT / ".venv"
STAMP = ROOT / ".deps-ok"
BUNDLE = "https://files.catbox.moe/62fvyh.zip"
BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3-flash-preview"


def log(m):
    print("[nova] " + str(m), flush=True)


def sh(cmd):
    log("$ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT))
    except Exception as e:
        log("gagal: %r" % (e,))
        return 1


def fetch():
    if (ROOT / "app" / "nova" / "cli.py").exists():
        log("bundle sudah ada")
        return True
    log("mengunduh bundle")
    z = ROOT / "_bundle.zip"
    urllib.request.urlretrieve(BUNDLE, z)
    with zipfile.ZipFile(z) as f:
        f.extractall(ROOT)
    z.unlink()
    return (ROOT / "app" / "nova" / "cli.py").exists()


def deps():
    vp = VENV / "bin" / "python"
    if STAMP.exists() and vp.exists():
        log("dependency siap")
        return vp
    if not vp.exists():
        if sh([sys.executable, "-m", "venv", str(VENV)]) != 0:
            log("venv gagal, pakai python sistem")
            vp = pathlib.Path(sys.executable)
    if vp.exists() and sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", "hermes-agent[messaging]==0.19.0"]) == 0:
        STAMP.write_text(str(int(time.time())))
        log("hermes-agent terpasang")
    else:
        log("pip gagal - gateway tidak akan jalan")
    return vp if vp.exists() else pathlib.Path(sys.executable)


def config():
    for d in ("", "skills", "logs"):
        (HOME / d).mkdir(parents=True, exist_ok=True)
    cfg = HOME / "config.yaml"
    cfg.write_text(
        "model:\n"
        "  default: " + MODEL + "\n"
        "  provider: custom\n"
        "  base_url: " + BASE + "\n"
        "  api_mode: chat_completions\n"
        "  key_env: NOVA_GEMINI_KEY\n"
        "providers:\n"
        "  custom:\n"
        "    name: google-ai-studio\n"
        "    base_url: " + BASE + "\n"
        "    model: " + MODEL + "\n"
        "    key_env: NOVA_GEMINI_KEY\n"
        "agent:\n"
        "  max_turns: 200\n"
        "terminal:\n"
        "  backend: local\n"
        "  timeout: 180\n"
        "memory:\n"
        "  memory_enabled: true\n"
        "  user_profile_enabled: true\n",
        encoding="utf-8")
    log("config.yaml ditulis")
    key = os.environ.get("NOVA_GEMINI_KEY", "")
    (HOME / ".env").write_text("NOVA_GEMINI_KEY=" + key + "\n", encoding="utf-8")
    log("hermes-home/.env ditulis (kunci: %s)" % ("ada" if key else "KOSONG"))
    src = ROOT / "skills" / "nova"
    dst = HOME / "skills" / "nova"
    if src.exists():
        import shutil
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        log("skill nova terpasang")


def main():
    log("python " + sys.version.split()[0])
    try:
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines()[:3]:
            log(line.strip())
    except Exception:
        pass
    if not fetch():
        return 2
    vp = deps()
    config()
    env = dict(os.environ)
    env["HERMES_HOME"] = str(HOME)
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = str(vp.parent) + os.pathsep + env.get("PATH", "")
    exe = vp.parent / "hermes"
    cmd = [exe, "gateway", "run"] if exe.exists() else [vp, "-m", "hermes_cli", "gateway", "run"]
    log("menjalankan gateway")
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
