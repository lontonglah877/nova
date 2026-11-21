# Deploy NOVA di server (24/7)

Tujuan: bot WhatsApp NOVA hidup di server, bukan di laptop.

## Yang perlu disiapkan di server

| Hal | Nilai |
|---|---|
| Repo | `https://github.com/lontonglah877/nova.git` |
| Perintah mulai | `python main.py` |
| Python | 3.11–3.14 (diuji 3.14.9) |
| Node.js | ≥ 20 (untuk WhatsApp bridge) |
| Variabel wajib | `NOVA_GEMINI_KEY` |
| Variabel opsional | `NOVA_OWNER` (nomor WhatsApp pemilik, format 62xxx) |
| Variabel opsional | `NOVA_WA_SESSION_B64` (base64 zip sesi WhatsApp hasil pairing) |
| Port | tidak perlu dibuka ke publik (bot keluar lewat WhatsApp) |

## Langkah

1. **Pairing WhatsApp sekali di mesin yang punya browser** (laptop juga boleh):
   ```bash
   pip install -r server/requirements.txt   # sekali saja
   cd server/whatsapp-bridge && npm install
   cd ../.. && python scripts/wa_pair_page.py
   ```
   Buka `http://127.0.0.1:8897`, pindai QR dengan WhatsApp → Perangkat tertaut.
   Sesi tersimpan di `_wa_tmp/session_qr`.

2. **Buat paket sesi untuk server**
   ```bash
   python scripts/export_wa_session.py
   ```
   Menghasilkan `nova-wa-session.zip` dan `nova-wa-session.b64`.
   Salin isi `.b64` ke secret server `NOVA_WA_SESSION_B64`. Jangan commit file ini.

3. **Deploy**
   - Botkeep: tempel repo GitHub, isi `NOVA_GEMINI_KEY` + `NOVA_WA_SESSION_B64`, start command `python main.py`.
   - VPS biasa (systemd): lihat `deploy/nova.service` dan `deploy/install.sh`.

4. **Verifikasi**
   ```bash
   curl -s localhost:3001/health        # {"status":"connected", ...}
   ```
   Lalu kirim pesan WhatsApp ke nomor bot; harus dibalas.

## Yang TIDAK dilakukan otomatis

- Memindai QR WhatsApp — hanya bisa dari HP pemilik nomor.
- Login / klik panel Botkeep — akun pengguna, bukan agen.
- Mengaktifkan layanan berbayar.

## Catatan penting

- **Satu bridge saja per sesi WhatsApp.** Dua proses memakai creds yang sama
  membuat WhatsApp menendang yang lama (`440 replaced`) dan bot tidak pernah stabil.
  Kalau menjalankan `python main.py` di server, jangan jalankan bridge manual di laptop
  dengan sesi yang sama.
- Hermes dipasang editable dari source (bukan wheel PyPI), karena wheel tidak memuat
  `scripts/whatsapp-bridge/bridge.js`.
