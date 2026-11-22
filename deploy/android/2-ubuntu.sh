#!/bin/bash
# STEP 2 — jalankan DI DALAM UBUNTU (proot). Root. Memasang dependensi + repo NOVA.
set -e
export DEBIAN_FRONTEND=noninteractive
echo "== NOVA di Android: tahap 2 (Ubuntu) =="
apt update
apt -y upgrade
apt install -y python3 python3-venv python3-pip git curl ca-certificates xz-utils tar build-essential unzip nano

echo "== ambil repo NOVA =="
mkdir -p /opt
cd /opt
if [ -d /opt/nova/.git ]; then
  cd /opt/nova && git fetch --depth 1 origin main && git reset --hard origin/main
else
  rm -rf /opt/nova
  git clone --depth 1 https://github.com/lontonglah877/nova.git /opt/nova
fi
cd /opt/nova

echo "== siapkan .env =="
if [ ! -f /opt/nova/.env ]; then
  cp /opt/nova/deploy/android/nova.env.example /opt/nova/.env
  chmod 600 /opt/nova/.env
  echo "BUAT /opt/nova/.env -> isi NOVA_GEMINI_KEY dan NOVA_WA_SESSION_B64"
else
  echo ".env sudah ada (tidak ditimpa)"
fi

echo "== sesi WhatsApp (kalau file .b64 disalin) =="
if [ -f /root/nova-hp/nova-wa-session.b64 ] && ! grep -q '^NOVA_WA_SESSION_B64=.\+' /opt/nova/.env 2>/dev/null; then
  B64=$(tr -d '\r\n' < /root/nova-hp/nova-wa-session.b64)
  printf 'NOVA_WA_SESSION_B64=%s\n' "$B64" >> /opt/nova/.env
  echo "sesi WhatsApp dimasukkan ke .env"
fi

chmod +x /root/nova-hp/run-nova.sh 2>/dev/null || true
echo "== tahap 2 selesai =="
echo "Berikutnya: nano /opt/nova/.env  (isi kunci API bila belum), lalu bash /root/nova-hp/run-nova.sh"
