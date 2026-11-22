#!/data/data/com.termux/files/usr/bin/bash
# STEP 1 — jalankan DI TERMUX (bukan di Ubuntu). Menyiapkan Ubuntu 24.04 + paket dasar.
set -e
echo "== NOVA di Android: tahap 1 (Termux) =="
pkg update -y
pkg upgrade -y
pkg install -y proot-distro termux-api git curl tar xz-utils
termux-wake-lock || true

echo "== pasang Ubuntu (lewati kalau sudah ada) =="
if ! proot-distro list --installed 2>/dev/null | grep -q ubuntu; then
  proot-distro install ubuntu
else
  echo "Ubuntu sudah terpasang"
fi

echo "== salin paket ke dalam Ubuntu (/root/nova-hp) =="
ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu"
if [ ! -d "$ROOTFS" ]; then
  echo "rootfs Ubuntu tidak ditemukan di $ROOTFS"
  exit 2
fi
mkdir -p "$ROOTFS/root/nova-hp"
cp -f "$HOME/nova-hp/"*.sh "$ROOTFS/root/nova-hp/" 2>/dev/null || true
cp -f "$HOME/nova-hp/"*.example "$ROOTFS/root/nova-hp/" 2>/dev/null || true
cp -f "$HOME/nova-hp/"*.md "$ROOTFS/root/nova-hp/" 2>/dev/null || true
if [ -f "$HOME/nova-hp/nova-wa-session.b64" ]; then
  cp -f "$HOME/nova-hp/nova-wa-session.b64" "$ROOTFS/root/nova-hp/"
  echo "sesi WhatsApp ikut disalin"
fi
chmod +x "$ROOTFS/root/nova-hp/"*.sh 2>/dev/null || true

echo "== jalankan tahap 2 di dalam Ubuntu =="
proot-distro login ubuntu -- bash /root/nova-hp/2-ubuntu.sh
echo "== tahap 1 selesai. Lanjut: bash ~/nova-hp/run-nova.sh =="
