#!/usr/bin/env python3
"""NOVA bootstrap for Botkeep (Python 3.13).

Downloads the NOVA source (GitHub zip, no git needed), prepares a venv,
installs Hermes, writes config + skill, then runs the gateway in the
foreground.

Env expected on the panel:
  NOVA_GEMINI_KEY  (required, secret)
"""
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
HOME = ROOT / "hermes-home"
VENV = ROOT / ".venv"
STAMP = ROOT / ".deps-ok"
SRC = ROOT / "_nova_src"
ZIP_URL = "https://github.com/lontonglah877/nova/archive/refs/heads/main.zip"
BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3-flash-preview"


def log(m):
    print("[nova] " + str(m), flush=True)


def load_env():
    """Botkeep writes panel variables to .env; os.environ may not carry them."""
    for cand in (ROOT / ".env", ROOT.parent / ".env"):
        try:
            if not cand.exists():
                continue
            for raw in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k] = v
            log("env loaded from " + str(cand))
        except Exception as exc:
            log("env read failed: %r" % (exc,))


def sh(cmd, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), **kw)
    except Exception as exc:
        log("failed: %r" % (exc,))
        return 1


def find_root(base):
    for cand in (base, base.parent):
        if (cand / "app" / "nova" / "cli.py").exists():
            return cand
    return None


def fetch():
    found = find_root(ROOT) or find_root(ROOT.parent)
    if found:
        log("source already present at " + str(found))
        return found
    log("downloading source zip")
    z = ROOT / "_src.zip"
    try:
        urllib.request.urlretrieve(ZIP_URL, z)
        shutil.rmtree(SRC, ignore_errors=True)
        SRC.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(SRC)
        z.unlink()
    except Exception as exc:
        log("download failed: %r" % (exc,))
        return None
    for child in sorted(SRC.iterdir()):
        if (child / "app" / "nova" / "cli.py").exists():
            log("extracted " + child.name)
            return child
    log("zip layout unexpected")
    return None


def deps():
    vp = VENV / "bin" / "python"
    if STAMP.exists() and vp.exists():
        log("deps ready")
        return vp
    if not vp.exists():
        if sh([sys.executable, "-m", "venv", str(VENV)]) != 0:
            log("venv failed; using system python")
            return pathlib.Path(sys.executable)
        vp = VENV / "bin" / "python"
    rc = sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q",
             "--upgrade", "pip", "setuptools", "wheel"])
    rc = rc or sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q",
                   "hermes-agent[messaging]==0.19.0"])
    if rc == 0:
        STAMP.write_text("ok")
        log("hermes-agent installed")
    else:
        log("pip install failed rc=%s" % rc)
    return vp


def config(src_root):
    for d in ("", "skills", "logs", "sessions"):
        (HOME / d).mkdir(parents=True, exist_ok=True)
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
        "  timeout: 180\n"
        "memory:\n"
        "  memory_enabled: true\n"
        "  user_profile_enabled: true\n",
        encoding="utf-8")
    key = os.environ.get("NOVA_GEMINI_KEY", "")
    (HOME / ".env").write_text("NOVA_GEMINI_KEY=" + key + "\n", encoding="utf-8")
    log("config written; key %s" % ("present" if key else "MISSING"))
    if src_root:
        for sdir in (src_root / "skills",):
            if sdir.exists():
                for item in sdir.iterdir():
                    if item.is_dir():
                        dst = HOME / "skills" / item.name
                        shutil.rmtree(dst, ignore_errors=True)
                        shutil.copytree(item, dst)
                        log("skill installed: " + item.name)


def main():
    log("start; python " + sys.version.split()[0])
    load_env()
    for p in ("/proc/meminfo",):
        try:
            log(pathlib.Path(p).read_text().splitlines()[0].strip())
        except Exception:
            pass
    src_root = fetch()
    if not src_root:
        log("no source; aborting")
        return 2
    vp = deps()
    config(src_root)
    env = dict(os.environ)
    env["HERMES_HOME"] = str(HOME)
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = str(vp.parent) + os.pathsep + env.get("PATH", "")
    exe = vp.parent / "hermes"
    cmd = [exe, "gateway", "run"] if exe.exists() else [vp, "-m", "hermes_cli", "gateway", "run"]
    log("starting gateway: " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
