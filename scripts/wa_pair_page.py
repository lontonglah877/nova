#!/usr/bin/env python3
"""Pairing WhatsApp NOVA + pasang sesi + jalankan bridge bot.

Alur:
  1. bridge --pair-only --pair-json di sesi sementara (_wa_tmp/session_qr)
  2. QR ditulis ke NOVA-QR.png dan disajikan di http://127.0.0.1:8897
  3. setelah HP memindai, creds dipasang ke PROFIL/whatsapp/session
  4. bridge mode bot dijalankan di port 3001 (dipakai Hermes gateway)
"""
import http.server
import json
import os
import pathlib
import shutil
import socketserver
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE_DIR = ROOT / "server" / "whatsapp-bridge"
BRIDGE = BRIDGE_DIR / "bridge.js"
HOME = pathlib.Path(
    os.environ.get("NOVA_HOME") or os.path.expandvars(r"%LOCALAPPDATA%\hermes\profiles\nova")
)
TARGETS = [HOME / "whatsapp" / "session", HOME / "platforms" / "whatsapp" / "session"]
SESI = pathlib.Path(os.environ.get("NOVA_PAIR_SESSION", str(ROOT / "_wa_tmp" / "session_qr")))
PNG = ROOT / "NOVA-QR.png"
PORT = int(os.environ.get("NOVA_PAIR_PORT", "8897"))
BOT_PORT = int(os.environ.get("NOVA_BOT_PORT", "3001"))

status = {"state": "menunggu", "user": "", "error": "", "bridge": "belum jalan"}
lock = threading.Lock()


def set_status(**kw):
    with lock:
        status.update(kw)


def node_exe():
    return shutil.which("node") or "node"


def qr_png_dari(data: str) -> bool:
    js = (
        "const {createRequire}=require('node:module');"
        "const r=createRequire(process.cwd()+'/tools/qr/x.js');"
        "const Q=r('qrcode');"
        f"Q.toFile({json.dumps(str(PNG))},{json.dumps(data)},{{width:640,margin:2}},(e)=>{{process.exit(e?1:0)}});"
    )
    try:
        return subprocess.call([node_exe(), "-e", js], cwd=str(ROOT), timeout=30) == 0
    except Exception:
        return False


def pasang_sesi() -> bool:
    if not (SESI / "creds.json").exists():
        return False
    for t in TARGETS:
        shutil.rmtree(t, ignore_errors=True)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SESI, t)
    set_status(bridge="sesi dipasang")
    return True


def jalankan_bot_bridge():
    log_path = ROOT / "_wa_tmp" / "bridge_bot.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "w", encoding="utf-8")
    p = subprocess.Popen(
        [node_exe(), str(BRIDGE), "--port", str(BOT_PORT), "--session", str(TARGETS[0]), "--mode", "bot"],
        cwd=str(BRIDGE_DIR), stdout=fh, stderr=subprocess.STDOUT, text=True,
    )
    set_status(bridge="bridge bot pid %d port %d" % (p.pid, BOT_PORT))


def pair():
    proc = subprocess.Popen(
        [node_exe(), str(BRIDGE), "--session", str(SESI), "--pair-only", "--pair-json"],
        cwd=str(BRIDGE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for line in proc.stdout:
        t = line.strip()
        if not t.startswith("{"):
            continue
        try:
            ev = json.loads(t)
        except Exception:
            continue
        jenis = ev.get("event")
        if jenis == "qr":
            set_status(state="qr")
            qr_png_dari(ev.get("qr") or "")
        elif jenis == "connected":
            set_status(state="terhubung", user=(ev.get("user") or {}).get("name") or "?")
            time.sleep(2)
            if pasang_sesi():
                jalankan_bot_bridge()
            break
        elif jenis == "error":
            set_status(state="gagal", error=str(ev.get("error")))
            break
    try:
        proc.terminate()
    except Exception:
        pass
    with lock:
        if status["state"] == "qr":
            status["state"] = "QR kedaluwarsa — muat ulang halaman"


PAGE = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Pairing WhatsApp NOVA</title><style>
body{margin:0;font-family:system-ui,Segoe UI,sans-serif;background:#0d1117;color:#e6edf3;display:flex;
flex-direction:column;align-items:center;justify-content:center;min-height:100vh;gap:14px;text-align:center}
h1{font-size:21px;margin:0;font-weight:600}
img{width:min(76vw,400px);height:auto;border-radius:14px;background:#fff;padding:10px}
p{margin:0;color:#8b949e;font-size:14px;max-width:520px;line-height:1.6}
kbd{background:#21262d;padding:2px 7px;border-radius:5px;font-size:13px}
#s{color:#2ea043;font-weight:600}
</style></head><body>
<h1>Pindai QR ini dengan WhatsApp</h1>
<img id="q" src="/qr.png" alt="QR">
<p>Di HP: <kbd>WhatsApp</kbd> &rarr; <kbd>Titik tiga</kbd> &rarr; <kbd>Perangkat tertaut</kbd> &rarr; <kbd>Tautkan perangkat</kbd></p>
<p id="s">status: memuat…</p>
<p>QR berganti sendiri tiap ~20 detik. Setelah terhubung, bridge bot langsung dijalankan.</p>
<script>
const q=document.getElementById('q'),s=document.getElementById('s');
setInterval(()=>{q.src='/qr.png?t='+Date.now();},2000);
setInterval(async()=>{try{const r=await fetch('/status');const j=await r.json();
s.textContent='status: '+j.state+(j.user?' ('+j.user+')':'')+(j.error?' — '+j.error:'')+' · '+j.bridge;}catch(e){}},2000);
</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def kirim(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/qr.png"):
            if PNG.exists():
                self.kirim(200, "image/png", PNG.read_bytes())
            else:
                self.kirim(404, "text/plain", b"no qr yet")
        elif self.path.startswith("/status"):
            with lock:
                self.kirim(200, "application/json", json.dumps(status).encode())
        else:
            self.kirim(200, "text/html; charset=utf-8", PAGE.encode())


def main():
    if not BRIDGE.exists():
        print("bridge.js tidak ada:", BRIDGE)
        return 2
    if not (BRIDGE_DIR / "node_modules").exists():
        print("node_modules belum ada; jalankan: cd", BRIDGE_DIR, "&& npm install")
        return 2
    SESI.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=pair, daemon=True).start()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as httpd:
        print(f"buka http://127.0.0.1:{PORT}/ lalu pindai QR")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
