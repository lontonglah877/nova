#!/usr/bin/env bash
# Pasang NOVA sebagai layanan systemd (VPS Linux). Jalankan sebagai root.
set -euo pipefail

REPO="${NOVA_REPO:-https://github.com/lontonglah877/nova.git}"
DIR="${NOVA_DIR:-/opt/nova}"
USER_NOVA="${NOVA_USER:-nova}"

id -u "$USER_NOVA" >/dev/null 2>&1 || useradd -r -m -d "/home/$USER_NOVA" -s /bin/bash "$USER_NOVA"

if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO" "$DIR"
fi
git -C "$DIR" fetch --all --prune
git -C "$DIR" reset --hard origin/main

python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --upgrade pip
"$DIR/.venv/bin/pip" install -r "$DIR/server/requirements.txt"

# Bridge WhatsApp (butuh Node >= 20)
if command -v npm >/dev/null 2>&1; then
  ( cd "$DIR/server/whatsapp-bridge" && npm install --omit=dev --no-audit --no-fund )
else
  echo "PERINGATAN: npm tidak ada; WhatsApp bridge tidak akan jalan" >&2
fi

if [ ! -f "$DIR/nova.env" ]; then
  cat > "$DIR/nova.env" <<'EOF'
# Isi dua baris berikut, lalu: systemctl restart nova
NOVA_GEMINI_KEY=
# NOVA_WA_SESSION_B64=
EOF
  chmod 600 "$DIR/nova.env"
  echo "EDIT DULU: $DIR/nova.env (isi NOVA_GEMINI_KEY), lalu jalankan ulang skrip ini"
fi

chown -R "$USER_NOVA":"$USER_NOVA" "$DIR"
install -m 644 "$DIR/deploy/nova.service" /etc/systemd/system/nova.service
sed -i "s#WorkingDirectory=/opt/nova#WorkingDirectory=$DIR#; s#ExecStart=/opt/nova/.venv/bin/python#ExecStart=$DIR/.venv/bin/python#; s#EnvironmentFile=/opt/nova/nova.env#EnvironmentFile=$DIR/nova.env#; s#User=nova#User=$USER_NOVA#" /etc/systemd/system/nova.service || true
grep -q "User=" /etc/systemd/system/nova.service || sed -i "/^WorkingDirectory=/i User=$USER_NOVA" /etc/systemd/system/nova.service

systemctl daemon-reload
systemctl enable --now nova
sleep 8
systemctl status nova --no-pager | head -20
echo
echo "health WhatsApp: curl -s localhost:3001/health"
echo "log:            journalctl -u nova -f"
