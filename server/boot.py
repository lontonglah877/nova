#!/usr/bin/env python3
"""NOVA bootstrap v3 for Botkeep (Python 3.13).

Alur:
  1. muat variabel panel (.env) dari ROOT / ROOT.parent
  2. unduh sumber NOVA (zip GitHub) bila belum ada
  3. unduh sumber Hermes (tarball commit yang sama dengan laptop) + venv + pip
  4. siapkan Node (unduh bila belum ada) + WhatsApp bridge (npm)
  5. pulihkan sesi WhatsApp yang sudah dipairing (nova-wa-session.zip)
  6. tulis config.yaml + hermes-home/.env
  7. jalankan gateway di foreground

Env panel yang dipakai:
  NOVA_GEMINI_KEY (wajib, rahasia) - boleh juga GEMINI_API_KEY
"""
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
HOME = ROOT / "hermes-home"
VENV = ROOT / ".venv"
STAMP = ROOT / ".deps-v3"
SRC = ROOT / "_nova_src"
TOOLS = ROOT / "tools"

NOVA_ZIP = "https://github.com/lontonglah877/nova/archive/refs/heads/main.zip"
HERMES_COMMIT = "c314285f077"
HERMES_TGZ = "https://github.com/NousResearch/hermes-agent/archive/" + HERMES_COMMIT + ".tar.gz"
FALLBACK_PKG = "hermes-agent[messaging]==0.19.0"
NODE_VER = "v22.14.0"

WA_ZIP = ROOT / "nova-wa-session.zip"
BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3-flash-preview"
OWNER = "6281216092537"
BOT_NUMBER = "628197654120"

UA = {"User-Agent": "nova-bootstrap/3"}


def log(m):
    print("[nova] " + str(m), flush=True)


def load_env():
    """Botkeep menulis variabel panel ke .env; os.environ belum tentu berisi."""
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
            log("env dibaca dari " + str(cand))
        except Exception as exc:
            log("env gagal dibaca: %r" % (exc,))


def sh(cmd, cwd=None, env=None):
    log("$ " + " ".join(str(c) for c in cmd))
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(cwd or ROOT), env=env)
    except Exception as exc:
        log("gagal: %r" % (exc,))
        return 1


def download(url, dest):
    log("unduh " + url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    log("  -> " + dest.name + " (" + str(dest.stat().st_size) + " byte)")
    return dest


def extract_zip(path, dest):
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        zf.extractall(dest)


def extract_tar(path, dest):
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            tf.extractall(dest)


def find_nova_root(base):
    for cand in (base, base.parent):
        if (cand / "app" / "nova" / "cli.py").exists():
            return cand
    return None


def fetch_nova():
    found = find_nova_root(ROOT) or find_nova_root(ROOT.parent)
    if found:
        log("sumber NOVA sudah ada: " + str(found))
        return found
    z = ROOT / "_src.zip"
    try:
        download(NOVA_ZIP, z)
        extract_zip(z, SRC)
        z.unlink()
    except Exception as exc:
        log("unduh NOVA gagal: %r" % (exc,))
        return None
    for child in sorted(SRC.iterdir()):
        if (child / "app" / "nova" / "cli.py").exists():
            log("NOVA diekstrak: " + child.name)
            return child
    log("layout zip NOVA tidak dikenal")
    return None


def fetch_hermes():
    """Unduh sumber Hermes (commit sama dengan laptop) - tanpa git."""
    marker = ROOT / "_hermes_src"
    if marker.exists():
        for child in sorted(marker.iterdir()):
            if (child / "hermes_cli").is_dir():
                log("sumber Hermes sudah ada: " + child.name)
                return child
    t = ROOT / "_hermes.tar.gz"
    try:
        download(HERMES_TGZ, t)
        extract_tar(t, marker)
        t.unlink()
    except Exception as exc:
        log("unduh Hermes gagal: %r" % (exc,))
        return None
    for child in sorted(marker.iterdir()):
        if (child / "hermes_cli").is_dir():
            log("Hermes diekstrak: " + child.name)
            return child
    return None


def venv_python():
    vp = VENV / "bin" / "python"
    if vp.exists():
        return vp
    if sh([sys.executable, "-m", "venv", str(VENV)]) != 0:
        log("venv gagal; pakai python sistem")
        return pathlib.Path(sys.executable)
    return VENV / "bin" / "python" if (VENV / "bin" / "python").exists() else pathlib.Path(sys.executable)


def deps(hsrc):
    vp = venv_python()
    if STAMP.exists() and (VENV / "bin" / "hermes").exists():
        log("dependensi siap (stamp)")
        return vp
    sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", "--upgrade", "pip", "setuptools", "wheel"])
    rc = 1
    if hsrc:
        rc = sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", str(hsrc) + "[messaging]"])
    if rc != 0:
        log("install dari sumber gagal; fallback PyPI")
        rc = sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", FALLBACK_PKG])
    if rc == 0:
        STAMP.write_text(str(int(time.time())))
        log("hermes-agent terpasang")
    else:
        log("pip gagal rc=" + str(rc))
    return vp


def node_bin():
    """Cari node; unduh bila belum ada. Kembalikan (node_exe, npm_cli_js)."""
    cands = [shutil.which("node"), str(TOOLS / "node" / "bin" / "node")]
    for cand in cands:
        if cand and pathlib.Path(cand).exists():
            p = pathlib.Path(cand)
            npm_cli = p.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
            log("node ditemukan: " + str(p))
            return p, (npm_cli if npm_cli.exists() else None)
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
    name = "node-" + NODE_VER + "-linux-" + arch
    url = "https://nodejs.org/dist/" + NODE_VER + "/" + name + ".tar.xz"
    t = ROOT / (name + ".tar.xz")
    try:
        download(url, t)
        with tarfile.open(t) as tf:
            tf.extractall(TOOLS)
        t.unlink()
    except Exception as exc:
        log("unduh node gagal: %r" % (exc,))
        return None, None
    exe = TOOLS / name / "bin" / "node"
    npm_cli = TOOLS / name / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    log("node siap: " + str(exe))
    return (exe if exe.exists() else None), (npm_cli if npm_cli.exists() else None)


def bridge(hsrc, node_exe, npm_cli):
    """Pasang WhatsApp bridge ke HERMES_HOME/scripts/whatsapp-bridge."""
    dst = HOME / "scripts" / "whatsapp-bridge"
    src = None
    cands = []
    if hsrc:
        cands.append(hsrc / "scripts" / "whatsapp-bridge")
    cands += [ROOT / "whatsapp-bridge", ROOT / "server" / "whatsapp-bridge"]
    for cand in cands:
        if (cand / "bridge.js").exists():
            src = cand
            break
    if not src:
        log("bridge.js tidak ditemukan; WhatsApp tidak bisa dipakai")
        return False
    if not (dst / "bridge.js").exists():
        log("menyalin bridge: " + str(src))
        shutil.rmtree(dst, ignore_errors=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("node_modules", "*.test.mjs", "__pycache__"))
    if (dst / "node_modules").exists():
        log("node_modules bridge sudah ada")
        return True
    if not node_exe:
        log("node tidak ada; npm install dilewati")
        return False
    env = dict(os.environ)
    env["PATH"] = str(node_exe.parent) + os.pathsep + env.get("PATH", "")
    if npm_cli and npm_cli.exists():
        cmd = [node_exe, npm_cli]
    else:
        cmd = [node_exe.parent / "npm"]
    if (dst / "package-lock.json").exists():
        rc = sh(cmd + ["ci", "--omit=dev", "--no-audit", "--no-fund"], cwd=dst, env=env)
    else:
        rc = sh(cmd + ["install", "--omit=dev", "--no-audit", "--no-fund"], cwd=dst, env=env)
    log("npm rc=" + str(rc))
    return (dst / "node_modules").exists()


def restore_session():
    """Pulihkan creds WhatsApp hasil pairing ke dua lokasi yang dipakai Hermes."""
    targets = (HOME / "whatsapp" / "session", HOME / "platforms" / "whatsapp" / "session")
    if any((t / "creds.json").exists() for t in targets):
        log("sesi WhatsApp sudah ada di server")
        return True
    if not WA_ZIP.exists():
        log("nova-wa-session.zip tidak ada; WhatsApp butuh pairing QR")
        return False
    tmp = ROOT / "_wa_tmp"
    try:
        extract_zip(WA_ZIP, tmp)
    except Exception as exc:
        log("ekstrak sesi gagal: %r" % (exc,))
        return False
    root = tmp
    if not (root / "creds.json").exists():
        for p in root.iterdir():
            if p.is_dir() and (p / "creds.json").exists():
                root = p
                break
    if not (root / "creds.json").exists():
        log("creds.json tidak ada di dalam zip")
        return False
    for t in targets:
        shutil.rmtree(t, ignore_errors=True)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, t)
        try:
            os.chmod(t, 0o700)
        except Exception:
            pass
        log("sesi dipulihkan ke " + str(t))
    shutil.rmtree(tmp, ignore_errors=True)
    return True


def api_key():
    for k in ("NOVA_GEMINI_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def config(nova_root, key):
    for d in ("", "skills", "logs", "sessions", "cron", "memories"):
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
    lines = [
        "NOVA_GEMINI_KEY=" + key,
        "WHATSAPP_ENABLED=true",
        "WHATSAPP_MODE=bot",
        "WHATSAPP_ALLOWED_USERS=" + OWNER,
        "HERMES_HOME=" + str(HOME),
        "PYTHONUNBUFFERED=1",
    ]
    (HOME / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("config.yaml + .env ditulis (kunci: " + ("ada" if key else "KOSONG") + ")")
    if nova_root:
        sdir = nova_root / "skills"
        if sdir.exists():
            for item in sdir.iterdir():
                if item.is_dir():
                    dst = HOME / "skills" / item.name
                    shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(item, dst)
                    log("skill terpasang: " + item.name)
        soul = nova_root / "SOUL.md"
        if soul.exists():
            shutil.copyfile(soul, HOME / "SOUL.md")
            log("SOUL.md terpasang")


def main():
    log("start; python " + sys.version.split()[0] + "; " + platform.machine())
    load_env()
    try:
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines()[:2]:
            log(line.strip())
    except Exception:
        pass

    nova_root = fetch_nova()
    if not nova_root:
        log("sumber NOVA tidak ada; berhenti")
        return 2
    hsrc = fetch_hermes()
    vp = deps(hsrc)
    node_exe, npm_cli = node_bin()
    bridge(hsrc, node_exe, npm_cli)
    restore_session()
    key = api_key()
    config(nova_root, key)

    env = dict(os.environ)
    env["HERMES_HOME"] = str(HOME)
    env["PYTHONUNBUFFERED"] = "1"
    env["WHATSAPP_ENABLED"] = "true"
    env["WHATSAPP_MODE"] = "bot"
    env["WHATSAPP_ALLOWED_USERS"] = OWNER
    path_bits = [str(vp.parent)]
    if node_exe:
        path_bits.insert(0, str(node_exe.parent))
    env["PATH"] = os.pathsep.join(path_bits) + os.pathsep + env.get("PATH", "")
    if key:
        env["NOVA_GEMINI_KEY"] = key

    exe = vp.parent / "hermes"
    cmd = [exe, "gateway", "run"] if exe.exists() else [vp, "-m", "hermes_cli", "gateway", "run"]
    log("menjalankan gateway: " + " ".join(str(c) for c in cmd))
    log("nomor bot: " + BOT_NUMBER + " | penerima: " + OWNER)
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
