#!/usr/bin/env python3
"""Ekspor sesi WhatsApp hasil pairing jadi zip + base64 untuk secret server."""
import base64
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SESI = pathlib.Path(__import__("os").environ.get("NOVA_PAIR_SESSION", str(ROOT / "_wa_tmp" / "session_qr")))
ZIP = ROOT / "nova-wa-session.zip"
B64 = ROOT / "nova-wa-session.b64"


def main() -> int:
    if not (SESI / "creds.json").exists():
        print("sesi belum ada:", SESI)
        print("jalankan dulu: python scripts/wa_pair_page.py lalu pindai QR")
        return 2
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in SESI.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(SESI))
    data = ZIP.read_bytes()
    B64.write_text(base64.b64encode(data).decode("ascii"), encoding="ascii")
    print("zip  :", ZIP, len(data), "byte")
    print("b64  :", B64, B64.stat().st_size, "char")
    print("pakai: salin isi .b64 ke secret NOVA_WA_SESSION_B64 di server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
