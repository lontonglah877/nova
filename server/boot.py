#!/usr/bin/env python3
"""NOVA bootstrap v5 for Botkeep (Python 3.14 via uv).

Alur:
  1. muat variabel panel (.env) dari ROOT / ROOT.parent
  2. unduh sumber NOVA (zip GitHub) bila belum ada
  3. unduh sumber Hermes (tarball commit yang sama dengan laptop)
  4. pasang uv, lalu Python 3.14 standalone ke ROOT/tools
  5. venv 3.14 (.venv314) + `uv pip install -e` sumber Hermes (editable)
  6. Node + WhatsApp bridge (npm) + pulihkan sesi pairing
  7. tulis config.yaml + hermes-home/.env
  8. jalankan gateway di foreground

Catatan penting:
  - hermes-agent MENOLAK build wheel/sdist (setup.py guard). Satu-satunya
    jalur resmi adalah editable install, karena itu `pip install <path>`
    selalu gagal dan jatuh ke PyPI 0.19.0 (versi lama -> perilaku beda).
  - pyproject Hermes hanya mendeklarasikan dependensi untuk python 3.14
    (marker `python_version >= '3.14'`). Di 3.13 dependensi inti tidak
    terpasang sama sekali -> venv harus 3.14.
  - venv baru memakai nama .venv314 supaya venv lama (.venv) tidak dihapus
    saat runtime masih berjalan.

Env panel yang dipakai:
  NOVA_GEMINI_KEY (wajib, rahasia) - boleh juga GEMINI_API_KEY
"""
import base64
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
VENV = ROOT / ".venv314"
STAMP = ROOT / ".deps-v5"
SRC = ROOT / "_nova_src"
TOOLS = ROOT / "tools"
HSRC = ROOT / "_hermes_src"

NOVA_ZIP = "https://github.com/lontonglah877/nova/archive/refs/heads/main.zip"
HERMES_COMMIT = "c314285f077"
HERMES_TGZ = "https://github.com/NousResearch/hermes-agent/archive/" + HERMES_COMMIT + ".tar.gz"
FALLBACK_PKG = "hermes-agent[messaging]==0.19.0"
NODE_VER = "v22.14.0"
PY_VER = "3.14"
UV_BASE = "https://github.com/astral-sh/uv/releases/latest/download/"
# Hanya yang dipakai jalur WhatsApp; extra [messaging] penuh menarik
# discord.py[voice]/telegram/slack yang tidak diperlukan di server ini.
EXTRA_PKGS = ["aiohttp", "qrcode", "brotlicffi"]

WA_ZIP = ROOT / "nova-wa-session.zip"
BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3-flash-preview"
OWNER = "6281216092537"
BOT_NUMBER = "628197654120"

UA = {"User-Agent": "nova-bootstrap/5"}


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
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    log("  -> " + dest.name + " (" + str(dest.stat().st_size) + " byte)")
    return dest


def extract_zip(path, dest, wipe=True):
    if wipe:
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        zf.extractall(dest)


def extract_tar(path, dest):
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
    for child in sorted(SRC.iterdir()) if SRC.exists() else []:
        if (child / "app" / "nova" / "cli.py").exists():
            log("sumber NOVA sudah ada: " + str(child))
            return child
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
    if HSRC.exists():
        for child in sorted(HSRC.iterdir()):
            if (child / "hermes_cli").is_dir():
                log("sumber Hermes sudah ada: " + child.name)
                return child
    t = ROOT / "_hermes.tar.gz"
    try:
        download(HERMES_TGZ, t)
        extract_tar(t, HSRC)
        t.unlink()
    except Exception as exc:
        log("unduh Hermes gagal: %r" % (exc,))
        return None
    for child in sorted(HSRC.iterdir()):
        if (child / "hermes_cli").is_dir():
            log("Hermes diekstrak: " + child.name)
            return child
    return None


def _arch_tag():
    machine = platform.machine().lower()
    return "aarch64" if machine in ("aarch64", "arm64") else "x86_64"


def uv_bin():
    """Cari/unduh biner uv (tidak butuh pip)."""
    found = shutil.which("uv")
    if found:
        log("uv ditemukan: " + found)
        return pathlib.Path(found)
    for cand in sorted(TOOLS.glob("uv*/uv")) if TOOLS.exists() else []:
        log("uv siap: " + str(cand))
        return cand
    if platform.system().lower() != "linux":
        log("uv unduhan otomatis hanya untuk linux")
        return None
    name = "uv-" + _arch_tag() + "-unknown-linux-gnu"
    t = ROOT / (name + ".tar.gz")
    try:
        download(UV_BASE + name + ".tar.gz", t)
        extract_tar(t, TOOLS)
        t.unlink()
    except Exception as exc:
        log("unduh uv gagal: %r" % (exc,))
        return None
    for cand in (TOOLS / name / "uv", TOOLS / "uv"):
        if cand.exists():
            try:
                os.chmod(cand, 0o755)
            except Exception:
                pass
            log("uv siap: " + str(cand))
            return cand
    log("uv tidak ditemukan setelah ekstrak")
    return None


def is_py314(vp):
    try:
        rc = subprocess.call([str(vp), "-c", "import sys;raise SystemExit(0 if sys.version_info[:2]==(3,14) else 1)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return rc == 0
    except Exception:
        return False


def venv_python(uv):
    """venv harus 3.14: dependensi Hermes hanya dideklarasikan untuk 3.14."""
    vp = VENV / "bin" / "python"
    if vp.exists():
        if is_py314(vp):
            log("venv 3.14 sudah ada")
            return vp
        log("venv ada tapi bukan 3.14; dibuat ulang")
        shutil.rmtree(VENV, ignore_errors=True)
    if uv:
        if sh([uv, "python", "install", PY_VER]) != 0:
            log("uv python install gagal (mungkin sudah ada)")
        if sh([uv, "venv", "--python", PY_VER, "--seed", str(VENV)]) != 0:
            log("uv venv gagal")
        if vp.exists() and is_py314(vp):
            log("venv 3.14 siap: " + str(vp))
            return vp
    log("venv 3.14 tidak tersedia; pakai python sistem " + sys.version.split()[0])
    return pathlib.Path(sys.executable)


def deps(hsrc, uv):
    vp = venv_python(uv)
    if not vp:
        return None
    if STAMP.exists() and (VENV / "bin" / "hermes").exists():
        log("dependensi siap (stamp)")
        return vp
    ed_ok = False
    if hsrc and uv:
        env = dict(os.environ)
        env.pop("HERMES_NIX_BUILD", None)
        # editable: build_editable tidak memicu guard bdist_wheel/sdist
        if sh([uv, "pip", "install", "--python", str(vp), "-q", "-e", str(hsrc)], env=env) == 0:
            if sh([uv, "pip", "install", "--python", str(vp), "-q"] + EXTRA_PKGS, env=env) == 0:
                ed_ok = True
        if ed_ok:
            rc = subprocess.call([str(vp), "-c", "import hermes_cli, qrcode"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if rc != 0:
                log("editable terpasang tapi import gagal")
                ed_ok = False
        if not ed_ok and (VENV / "bin" / "python").exists():
            log("coba pip editable")
            if sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", "-e", str(hsrc)]) == 0:
                ed_ok = True
    if ed_ok:
        STAMP.write_text(str(int(time.time())))
        log("hermes-agent editable (3.14) terpasang")
        return vp
    log("editable gagal; fallback PyPI " + FALLBACK_PKG)
    if sh([vp, "-m", "pip", "install", "--no-cache-dir", "-q", FALLBACK_PKG]) == 0:
        STAMP.write_text(str(int(time.time())))
        log("hermes-agent PyPI terpasang (versi lama)")
    return vp


def node_bin():
    """Cari node; unduh bila belum ada. Kembalikan (node_exe, npm_cli_js)."""
    cands = [shutil.which("node")]
    if TOOLS.exists():
        cands += [str(p) for p in sorted(TOOLS.glob("node*/bin/node"))]
        cands += [str(TOOLS / "node" / "bin" / "node")]
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
        extract_tar(t, TOOLS)
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


def restore_session() -> bool:
    """Pulihkan creds WhatsApp hasil pairing ke dua lokasi yang dipakai Hermes.

    Tiga sumber, berurutan:
      1. sesi sudah ada di disk server,
      2. `NOVA_WA_SESSION_B64` (secret Botkeep: base64 dari zip creds),
      3. `nova-wa-session.zip` di root (untuk deploy manual).
    Tanpa salah satu dari itu, bridge akan meminta pairing QR di Console.
    """
    targets = (HOME / "whatsapp" / "session", HOME / "platforms" / "whatsapp" / "session")
    if any((t / "creds.json").exists() for t in targets):
        log("sesi WhatsApp sudah ada di server")
        return True

    blob = os.environ.get("NOVA_WA_SESSION_B64", "").strip()
    if blob:
        tmp = ROOT / "_wa_tmp"
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(blob)
            zpath = ROOT / "_wa_session.zip"
            zpath.write_bytes(data)
            extract_zip(zpath, tmp)
            zpath.unlink()
            log("sesi WhatsApp dari NOVA_WA_SESSION_B64 (" + str(len(data)) + " byte)")
        except Exception as exc:
            log("NOVA_WA_SESSION_B64 tidak terbaca: %r" % (exc,))
            blob = ""
        if blob:
            return _install_session(tmp, targets)

    if not WA_ZIP.exists():
        log("sesi WhatsApp belum ada; bridge akan minta pairing QR di Console")
        return False
    tmp = ROOT / "_wa_tmp"
    try:
        extract_zip(WA_ZIP, tmp)
    except Exception as exc:
        log("ekstrak sesi gagal: %r" % (exc,))
        return False
    return _install_session(tmp, targets)


def _install_session(tmp, targets) -> bool:
    root = tmp
    if not (root / "creds.json").exists():
        for p in root.iterdir():
            if p.is_dir() and (p / "creds.json").exists():
                root = p
                break
    if not (root / "creds.json").exists():
        log("creds.json tidak ada di dalam sumber sesi")
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    for t in targets:
        shutil.rmtree(t, ignore_errors=True)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, t, ignore=shutil.ignore_patterns("tmp*"))
        try:
            os.chmod(t, 0o700)
        except Exception:
            pass
        log("sesi dipulihkan ke " + str(t))
    shutil.rmtree(tmp, ignore_errors=True)
    return True


def pair_if_needed(node_exe, npm_cli) -> bool:
    """Pairing sekali di Console panel kalau creds server belum ada.

    Bridge dijalankan mode `--pair-only` dengan stdout diwarisi, jadi QR
    tercetak langsung di Console Botkeep dan bisa dipindai dari HP. Setelah
    creds tersimpan, fungsi ini keluar dan gateway memakai sesi itu.
    """
    sesi = HOME / "whatsapp" / "session"
    if (sesi / "creds.json").exists():
        return True
    if not node_exe:
        log("node tidak ada; pairing tidak bisa dijalankan")
        return False
    script = HOME / "scripts" / "whatsapp-bridge" / "bridge.js"
    if not script.exists():
        script = ROOT / "server" / "whatsapp-bridge" / "bridge.js"
    if not script.exists():
        log("bridge.js tidak ada; pairing dilewati")
        return False
    sesi.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(node_exe.parent) + os.pathsep + env.get("PATH", "")
    log("=" * 62)
    log("PAIRING WHATSAPP: pindai QR di bawah dengan WhatsApp > Perangkat tertaut")
    log("=" * 62)
    cmd = [str(node_exe), str(script), "--port", "3000", "--session", str(sesi),
           "--mode", "bot", "--pair-only"]
    timeout = int(os.environ.get("NOVA_PAIR_WAIT", "240") or 240)
    try:
        proc = subprocess.Popen(cmd, cwd=str(script.parent), env=env)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log("pairing melewati batas %d detik; lanjut tanpa WhatsApp" % timeout)
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
    except Exception as exc:
        log("pairing gagal: %r" % (exc,))
        return False
    ok = (sesi / "creds.json").exists()
    log("creds WhatsApp: " + ("ADA" if ok else "BELUM ADA"))
    return ok


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
    uv = uv_bin()
    vp = deps(hsrc, uv)
    if not vp:
        log("venv/dependensi tidak siap; berhenti")
        return 3
    node_exe, npm_cli = node_bin()
    bridge(hsrc, node_exe, npm_cli)
    restore_session()
    if not pair_if_needed(node_exe, npm_cli):
        log("PERINGATAN: WhatsApp belum tertaut; bot akan jalan tanpa WhatsApp sampai pairing selesai")
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

    exe = VENV / "bin" / "hermes"
    if exe.exists():
        cmd = [exe, "gateway", "run"]
    else:
        # hermes_cli tidak punya __main__.py: entry point-nya hermes_cli.main:main
        cmd = [vp, "-c", "from hermes_cli.main import main; main()", "gateway", "run"]
    log("menjalankan gateway: " + " ".join(str(c) for c in cmd))
    log("nomor bot: " + BOT_NUMBER + " | penerima: " + OWNER)
    try:
        return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
