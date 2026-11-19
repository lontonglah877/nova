#!/usr/bin/env bash
# NOVA — deploy/verification helper for a fresh server (panel bot hosting).
# Read-only by default: every step only *reports* unless you pass --apply.
set -uo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

say "== 1. Lingkungan =="
say "OS      : $(uname -srm 2>/dev/null || echo unknown)"
say "Kernel  : $(uname -r 2>/dev/null || echo unknown)"
say "RAM     : $(( ($(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}') + 1023) / 1024 )) MB"
say "vCPU    : $(nproc 2>/dev/null || echo '?')"
say "Disk    : $(df -h / 2>/dev/null | awk 'NR==2 {print $2" total, "$4" free"}')"
say "UID     : $(id -u) (0 = root)"
say "PID 1   : $( [ -r /proc/1/cmdline ] && tr '\0' ' ' </proc/1/cmdline | cut -c1-60 || echo 'n/a (non-Linux)' )"
say "Init    : $( [ -d /run/systemd/system ] && echo systemd || echo 'no systemd' )"
have python3 && say "python3 : $(python3 -VV 2>&1 | head -1)" || say "python3 : TIDAK ADA"
have node && say "node    : $(node --version)" || say "node    : TIDAK ADA"
have npm && say "npm     : $(npm --version)" || say "npm     : TIDAK ADA"
have git && say "git     : $(git --version)" || say "git     : tidak ada"

say
say "== 2. Jaringan =="
have curl && say "IPv4 keluar: $(curl -4 -sS -m 10 -o /dev/null -w '%{http_code}' https://web.whatsapp.com || echo GAGAL)"
have curl && say "IPv6 keluar: $(curl -6 -sS -m 10 -o /dev/null -w '%{http_code}' https://web.whatsapp.com || echo GAGAL)"
have curl && say "IPv6 DNS   : $(getent ahostsv6 web.whatsapp.com >/dev/null 2>&1 && echo ada || echo tidak ada)"

say
say "== 3. Persistensi proses =="
say "Kalau PID 1 bukan systemd dan tidak ada supervisor, proses yang kamu jalankan hanya hidup"
say "selama sesi terminal panel. Untuk 24/7 perlu tab 'startup command' panel atau supervisor."

say
say "== 4. Footprint NOVA =="
ROOT="${NOVA_ROOT:-$HOME/nova}"
if [ -d "$ROOT" ]; then
  say "NOVA root: $ROOT ($(du -sh "$ROOT" 2>/dev/null | cut -f1))"
else
  say "NOVA root: $ROOT BELUM ADA (perlu upload/clone)"
fi

if [ "$APPLY" = "1" ]; then
  say
  say "== 5. Terapkan =="
  if [ -d "$ROOT" ]; then
    NOVA_HOME="$ROOT" python3 "$ROOT/app/nova/cli.py" db init && say "  db init OK"
    NOVA_HOME="$ROOT" python3 "$ROOT/app/nova/cli.py" system check
  else
    say "  dilewati: $ROOT tidak ada"
  fi
else
  say
  say "(mode baca-saja; jalankan dengan --apply untuk db init + system check)"
fi
