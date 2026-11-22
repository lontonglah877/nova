#!/bin/bash
# STEP 3 — jalankan DI DALAM UBUNTU. Menyalakan NOVA (gateway + WhatsApp).
# Hentikan dengan Ctrl+C. Untuk 24/7 gunakan boot-nova.sh dari Termux:Boot.
set -e
if [ -f /opt/nova/.env ]; then
  set -a
  . /opt/nova/.env
  set +a
fi
if [ -z "$NOVA_GEMINI_KEY" ]; then
  echo "NOVA_GEMINI_KEY kosong. Jalankan: nano /opt/nova/.env lalu isi kuncinya."
  exit 2
fi
cd /opt/nova
echo "== NOVA start: $(date '+%Y-%m-%d %H:%M:%S') =="
exec python3 main.py
