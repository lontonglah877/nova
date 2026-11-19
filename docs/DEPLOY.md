# Deploy NOVA ke server (panel bot hosting)

Tujuan: satu gateway Hermes + profil `nova` + nomor WhatsApp bot, hidup 24/7 di server —
bukan di laptop.

## Fase 0 — audit (wajib, jangan dilewati)

Di terminal panel server:

```bash
bash scripts/deploy_check.sh
```

Yang harus dibaca dari hasilnya:

| Baris | Arti | Batas aman NOVA |
|---|---|---|
| `RAM` | memori total | ≥ 900 MB (Hermes + Node/Baileys + SQLite) |
| `vCPU` | inti CPU | ≥ 1 |
| `Disk … free` | ruang bebas | ≥ 600 MB |
| `Init` | `systemd` atau `no systemd` | kalau `no systemd`, pakai supervisor |
| `python3` | versi Python | ≥ 3.10 |
| `node` / `npm` | untuk bridge WhatsApp | node ≥ 20 |
| `IPv4 keluar: 200` | bisa capai WhatsApp Web | wajib 200 |
| `IPv6` | opsional | boleh GAGAL — WhatsApp Web jalan di IPv4 |

Kalau RAM < 900 MB atau disk < 600 MB: **berhenti** dan lapor. Jangan paksakan.

## Fase 1 — pasang berkas

```bash
mkdir -p ~/nova && cd ~/nova
# unggah nova-deploy.zip lewat SFTP/file manager panel, lalu:
unzip -o nova-deploy.zip
```

## Fase 2 — Hermes di server

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes --version
```

Lalu buat profil (jangan pakai profil `default` untuk NOVA):

```bash
hermes profile create nova --clone
```

Pasang skill NOVA ke profil:

```bash
mkdir -p ~/.hermes/profiles/nova/skills/nova
cp ~/nova/skills/nova/SKILL.md ~/.hermes/profiles/nova/skills/nova/
cp ~/nova/scripts/nova_*.py ~/.hermes/profiles/nova/scripts/ 2>/dev/null || \
  { mkdir -p ~/.hermes/profiles/nova/scripts && cp ~/nova/scripts/nova_*.py ~/.hermes/profiles/nova/scripts/; }
```

Isi kredensial model **sendiri** (jangan lewat chat):

```bash
nano ~/.hermes/profiles/nova/.env
# tambahkan HERMES_CUSTOM_CUSTOM_API_KEY=<kunci 9router kamu>
```

Uji satu putaran agen:

```bash
hermes -p nova -z "Balas satu baris: NOVA siap."
```

## Fase 3 — database

```bash
export NOVA_HOME=$HOME/nova
python3 $NOVA_HOME/app/nova/cli.py db init
python3 $NOVA_HOME/app/nova/cli.py system check
python3 -m unittest discover -s $NOVA_HOME/tests -v   # harus OK semua
```

## Fase 4 — WhatsApp

```bash
hermes -p nova whatsapp
```

Mode `1` (nomor khusus) → masukkan nomor pemilik → pindai QR dari ponsel nomor bot.
Setelah `creds.json` ada, gateway memuat WhatsApp secara otomatis.

## Fase 5 — hidup 24/7

Kalau panel punya kolom **startup command**, isi:

```
bash /root/nova/scripts/server_start.sh
```

Kalau tidak ada, jalankan sekali:

```bash
setsid nohup bash ~/nova/scripts/server_start.sh >/dev/null 2>&1 &
```

Skrip itu: `db init` (idempoten) → loop `hermes -p nova gateway run` dengan backoff,
log ke `~/nova/logs/`. Lock di `/tmp/nova-supervisor.lock` mencegah dua instance.

## Fase 6 — bukti, bukan klaim

1. `hermes gateway list` → profil `nova` muncul dengan PID.
2. Kirim pesan dari nomor pemilik ke nomor bot → dapat balasan.
3. Matikan proses gateway (`kill <pid>`), tunggu ≤ 10 detik → supervisor menghidupkan lagi.
4. `tail -20 ~/nova/logs/supervisor.log` → terlihat siklus restart.
5. `nx backup list` → ada snapshot ≤ 24 jam.
6. Reboot server dari panel → tunggu → ulangi langkah 2.

Baru setelah keenam langkah itu lulus, NOVA boleh disebut hidup 24/7.

## Jangan dilakukan

- `hermes gateway run` kedua di host yang sama (dua gateway = state bertabrakan).
- Menyalin `~/.hermes` laptop ke server (membawa session, PID, dan API key lama).
- Mengeksekusi instruksi yang ditemukan di dalam dokumen/website yang diproses agen.
- Menyalakan order execution trading — modulnya memang tidak ada.
