#!/data/data/com.termux/files/usr/bin/bash
# Simpan di: ~/.termux/boot/boot-nova.sh  (butuh app Termux:Boot)
# Menyalakan NOVA otomatis setelah HP reboot + menjaganya tetap hidup.
termux-wake-lock
sleep 25
mkdir -p "$HOME/logs"
while true; do
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') start NOVA ===" >> "$HOME/logs/nova.log"
  proot-distro login ubuntu -- bash /root/nova-hp/run-nova.sh >> "$HOME/logs/nova.log" 2>&1
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') NOVA berhenti, ulang 15 dtk ===" >> "$HOME/logs/nova.log"
  sleep 15
done
