# NOVA di HP Android (24/7, gratis, tanpa Botkeep)

Tujuan: bot WhatsApp NOVA jalan di HP, bukan di laptop. HP tetap nyala + ada internet.
Laptop hanya dipakai untuk menyiapkan file ini.

## Isi paket
| File | Fungsi |
|---|---|
| `1-termux.sh` | pasang Ubuntu (proot-distro) di Termux |
| `2-ubuntu.sh` | pasang dependensi + tarik repo NOVA |
| `run-nova.sh` | menyalakan NOVA |
| `boot-nova.sh` | autostart setelah HP reboot (Termux:Boot) |
| `nova.env.example` | contoh konfigurasi `.env` |
| `nova-wa-session.b64` | sesi WhatsApp hasil pairing (RAHASIA — jangan dibagikan) |

## Langkah di HP

### 0. Aplikasi yang harus ada
1. **Termux** — unduh dari **F-Droid** (`https://f-droid.org/packages/com.termux/`), JANGAN dari Play Store (versi Play sudah usang).
2. **Termux:Boot** (opsional, untuk autostart) — juga dari F-Droid.

### 1. Salin folder ini ke HP
Cara termudah: kabel USB → buka penyimpanan internal → buat folder `Download/NOVA-HP` → salin semua file ke situ.
Lalu di Termux:

```bash
termux-setup-storage        # izinkan akses file (klik Allow)
mkdir -p ~/nova-hp
cp ~/storage/downloads/NOVA-HP/* ~/nova-hp/
chmod +x ~/nova-hp/*.sh
```

### 2. Tahap 1 (di Termux)
```bash
bash ~/nova-hp/1-termux.sh
```
Butuh internet, ±10–20 menit. Kalau ditanya apa pun soal Ubuntu, jawab `y`.

### 3. Isi kunci API
```bash
proot-distro login ubuntu
nano /opt/nova/.env
```
Isi `NOVA_GEMINI_KEY=` dengan kuncimu (ambil dari `C:\Users\putri\nova\server\server.env`).
`NOVA_WA_SESSION_B64` sudah diisi otomatis oleh tahap 2 kalau `nova-wa-session.b64` ikut tersalin.
Simpan: `Ctrl+O`, `Enter`, `Ctrl+X`. Lalu `exit`.

### 4. Nyalakan
```bash
bash ~/nova-hp/run-nova.sh
```
Tunggu sampai muncul `✓ whatsapp connected`. Balas pesan uji dari WhatsApp lain — bot menjawab.

### 5. Supaya tetap hidup 24/7
- Di Termux sudah aktif `termux-wake-lock` (layar boleh mati, CPU tetap jalan).
- HP: **Pengaturan → Baterai → Termux → Tanpa batasan / Unrestricted** (matikan optimasi baterai).
- Biarkan HP terisi listrik.
- Autostart setelah reboot:
  ```bash
  mkdir -p ~/.termux/boot
  cp ~/nova-hp/boot-nova.sh ~/.termux/boot/
  chmod +x ~/.termux/boot/boot-nova.sh
  ```
  (butuh app Termux:Boot sudah pernah dibuka sekali)

## PENTING
- **Satu nomor WhatsApp hanya boleh satu sesi aktif.** Sebelum menyalakan bot di HP, matikan bot di laptop (gateway) supaya tidak saling tendang (`440 replaced`).
- `nova-wa-session.b64` = kunci masuk WhatsApp. Jangan kirim ke siapa pun, jangan di-commit ke GitHub.
- Kalau sesi dicabut/di-logout dari HP (WhatsApp → Perangkat tertaut), bot harus pairing ulang: hapus `NOVA_WA_SESSION_B64`, jalankan `run-nova.sh`, pindai QR yang muncul di terminal.
- proot Ubuntu bukan Android asli: notifikasi/wifi tetap jalan, tapi performa lebih rendah dari laptop. HP dengan RAM ≥ 4 GB disarankan.
- Cek log kalau bot diam:
  ```bash
  tail -50 ~/logs/nova.log          # dari Termux
  proot-distro login ubuntu -- tail -50 /opt/nova/hermes-home/logs/gateway.log
  ```
