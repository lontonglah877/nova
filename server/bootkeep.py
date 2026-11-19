#!/usr/bin/env python3
"""NOVA bootstrap for Botkeep (Python 3.13).

Clones NOVA from GitHub, builds a venv, installs Hermes, writes config +
skill, then runs the gateway in the foreground.

Env expected on the panel:
  NOVA_GEMINI_KEY  (required, secret)
  NOVA_REPO        (optional, default below)
"""
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT / "_nova_src"
HOME = ROOT / "hermes-home"
VENV = ROOT / ".venv"
STAMP = ROOT / ".deps-ok"
DEFAULT_REPO = "https://github.com/lontonglah877/nova.git"
BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3-flash-preview"


def log(msg):
    print("[nova] " + str(msg), flush=True)


def run(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), **kw)
    except Exception as exc:
        log("failed: %r" % (exc,))
        return 1


def clone():
    # GitHub sync may already have placed the repo one level above this file.
    for cand in (ROOT, ROOT.parent):
        if (cand / "app" / "nova" / "cli.py").exists():
            log("source already present at " + str(cand))
            return True
    url = os.environ.get("NOVA_REPO") or DEFAULT_REPO
    shutil.rmtree(REPO, ignore_errors=True)
    if run(["git", "clone", "--depth", "1", url, str(REPO)]) != 0:
        log("git clone failed")
        return False
    return (REPO / "app" / "nova" / "cli.py").exists()


def deps():
    vp = VENV / "bin" / "python"
    if not vp.exists():
        if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
            log("venv failed; using system python")
            return pathlib.Path(sys.executable)
        vp = VENV / "bin" / "python"
    if STAMP.exists():
        log("deps already installed")
        return vp
    rc = run([vp, "-m", "pip", "install", "--no-cache-dir", "-q",
              "--upgrade", "pip", "setuptools", "wheel"])
    rc = rc or run([vp, "-m", "pip", "install", "--no-cache-dir", "-q",
                    "hermes-agent[messaging]==0.19.0"])
    if rc == 0:
        STAMP.write_text("ok")
        log("hermes-agent installed")
    else:
        log("pip install failed rc=%s" % rc)
    return vp


def config():
    for sub in ("", "skills", "logs", "sessions"):
        (HOME / sub).mkdir(parents=True, exist_ok=True)
    (HOME / "config.yaml").write_text(
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
        "  timeout: 180\n",
        encoding="utf-8")
    key = os.environ.get("NOVA_GEMINI_KEY", "")
    (HOME / ".env").write_text("NOVA_GEMINI_KEY=" + key + "\n", encoding="utf-8")
    log("config written; key %s" % ("present" if key else "MISSING"))
    src = REPO / "skills" / "nova"
    if src.exists():
        dst = HOME / "skills" / "nova"
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        log("nova skill installed")


def main():
    log("start; python " + sys.version.split()[0])
    try:
        log(pathlib.Path("/proc/meminfo").read_text().splitlines()[0])
    except Exception:
        pass
    if not clone():
        return 2
    vp = deps()
    config()
    env = dict(os.environ)
    env["HERMES_HOME"] = str(HOME)
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = str(vp.parent) + os.pathsep + env.get("PATH", "")
    exe = vp.parent / "hermes"
    cmd = [str(exe), "gateway", "run"] if exe.exists() else [str(vp), "-m", "hermes_cli", "gateway", "run"]
    log("starting gateway: " + " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
