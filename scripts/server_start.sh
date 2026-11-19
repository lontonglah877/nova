#!/usr/bin/env bash
# NOVA — supervisor untuk server tanpa systemd (panel bot hosting).
#
# Pakai sebagai "startup command" panel, atau jalankan sekali dengan:
#   setsid nohup bash scripts/server_start.sh >/dev/null 2>&1 &
#
# Kenapa supervisor, bukan sekadar `hermes gateway run`:
#   panel bot hosting biasanya hanya menjalankan satu proses dan tidak menghidupkannya
#   kembali kalau mati. Loop ini yang memberi perilaku 24/7.
#
# Yang TIDAK dilakukan skrip ini: menjalankan dua gateway. Lock file di bawah menjaga
# hanya satu instance per HERMES_HOME yang hidup.
set -uo pipefail

NOVA_ROOT="${NOVA_ROOT:-$HOME/nova}"
export NOVA_HOME="${NOVA_HOME:-$NOVA_ROOT}"
export NOVA_ROOT
export NOVA_WORKSPACE="${NOVA_WORKSPACE:-$NOVA_ROOT/workspace}"
export NOVA_DB="${NOVA_DB:-$NOVA_HOME/data/nova.sqlite}"
export HERMES_PROFILE="${HERMES_PROFILE:-nova}"
export TZ="${TZ:-Asia/Jakarta}"
export PYTHONUNBUFFERED=1

LOG_DIR="${LOG_DIR:-$NOVA_ROOT/logs}"
LOCK="/tmp/nova-supervisor.lock"
mkdir -p "$LOG_DIR" "$NOVA_HOME/data" "$NOVA_WORKSPACE" "$(dirname "$NOVA_DB")"

log() { printf '%s [sup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_DIR/supervisor.log"; }

if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  log "sudah berjalan (pid $(cat "$LOCK")), keluar"
  exit 0
fi
echo $$ > "$LOCK"
trap 'log "berhenti"; rm -f "$LOCK"; exit 0' INT TERM

# 1. Pastikan database siap (idempoten).
if ! python3 "$NOVA_ROOT/app/nova/cli.py" db init >>"$LOG_DIR/supervisor.log" 2>&1; then
  log "FATAL: db init gagal — cek $LOG_DIR/supervisor.log"
  rm -f "$LOCK"; exit 1
fi
log "db siap: $NOVA_DB"

# 2. Loop supervisor.
BACKOFF=5
while true; do
  log "menjalankan gateway profil=$HERMES_PROFILE"
  hermes -p "$HERMES_PROFILE" gateway run >>"$LOG_DIR/gateway.out" 2>&1
  code=$?
  log "gateway keluar dengan kode $code; ulang dalam ${BACKOFF}s"
  sleep "$BACKOFF"
  # backoff eksponensial sampai 60s, reset kalau sempat hidup lama tidak dilacak —
  # sederhana dan cukup: naik bertahap.
  BACKOFF=$(( BACKOFF < 60 ? BACKOFF * 2 : 60 ))
done
