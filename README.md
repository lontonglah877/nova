# NOVA — Personal AI Assistant

Satu asisten pribadi lewat satu nomor WhatsApp: life management, belajar kedokteran,
pasar read-only, memori & dokumen, riset, eksekusi proyek, dan otomasi.

Mesinnya **stdlib-only Python** (tanpa dependensi pihak ketiga) supaya ringan di container
1 GB, dengan SQLite sebagai satu-satunya penyimpanan.

## Bentuk sistem

```
WhatsApp (nomor bot)
   ↓  Baileys bridge (Node)
Hermes Gateway  →  profil `nova`  →  agen utama + Skills
   ↓
nx CLI  →  app/nova/services/*.py  →  data/nova.sqlite
```

Satu gateway · satu profil · satu agen · banyak Skills. Detail: `docs/ARCHITECTURE.md`.

## Mulai cepat

```bash
# 1. Health check lingkungan (baca-saja)
bash scripts/deploy_check.sh

# 2. Siapkan database
nx db init

# 3. Coba mesinnya
nx inbox add --args '{"title":"Ide pertama","kind":"idea"}'
nx task  add --args '{"title":"Baca patofisiologi kolangitis","priority":2,"due_at":"2026-11-19T21:00:00+07:00"}'
nx review daily --args '{}'

# 4. Semua perintah
nx commands
```

Launcher: `nx` (Git-Bash/macOS/Linux) atau `nx.bat` (Windows), keduanya di
`~/.local/bin`. Tanpa launcher:

```bash
NOVA_HOME=~/nova python app/nova/cli.py <domain> <action> --args '<json>'
```

## Tes

```bash
python -m unittest discover -s tests -v
```

47 tes: migrasi, inbox, task, goal, reminder, belajar SM-2, trading read-only,
dokumen, proyek, backup/restore, monitoring, dan kontrak CLI (exit code + JSON).

## Peta berkas

```
app/nova/
  cli.py            antarmuka JSON tunggal (domain → fungsi)
  db.py             SQLite, migrasi berversi, transaksi, idempotensi
  util.py           id, waktu UTC, tampilan WIB, helper JSON
  concepts.py       kartu belajar awal (kolangitis, koledokolitiasis)
  services/
    life.py         inbox, task, goal, milestone, reminder, note, review
    learning.py     topik, flashcard SM-2, attempt, progres
    trading.py      watchlist, snapshot, sinyal, jurnal, performa (read-only)
    documents.py    intake file, ekstraksi teks, tag
    projects.py     workspace, task proyek, decision log
    backup.py       snapshot SQLite konsisten + uji pulih
    monitoring.py   health check, watchdog, audit log
docs/               ARCHITECTURE · COMMANDS · WHATSAPP
scripts/            deploy_check.sh
skills/nova/        SKILL.md untuk profil Hermes `nova`
data/               nova.sqlite (dibuat saat `db init`)
```

## Invarian yang dijaga kode

1. Waktu disimpan UTC, ditampilkan WIB. Input tanpa zona ditolak.
2. Operasi tulis menerima kunci idempotensi — kirim ulang tidak menggandakan data.
3. Snapshot pasar wajib `source` + `observed_at`.
4. Tidak ada fungsi order/withdraw di modul trading (`tests` memeriksanya).
5. Migrasi append-only.
6. DB NOVA terpisah dari `~/.hermes/state.db`.

## Status

| Bagian | Status | Bukti |
|---|---|---|
| Mesin data + CLI | **selesai** | 47 tes lulus (ulang di salinan bersih juga OK) |
| Skill agen (`skills/nova`) | **selesai** | terpasang di profil `nova` |
| Profil Hermes `nova` | **jalan** | `hermes -p nova -z …` → agen memanggil CLI dan membuat task nyata (`task_e831a296a57d`) |
| Cron: daily brief 06:00, backup 02:00, watchdog 30m | **terdaftar & teruji** | run `4943bf31…` completed, `20af4591…` completed |
| Paket deploy | **siap** | `~/Desktop/nova-deploy.zip` (28 berkas) |
| Pairing WhatsApp | **menunggu nomor bot final** | wizard `hermes -p nova whatsapp` belum dijalankan |
| Deploy ke server Botkeep | **menunggu akses panel** | `botkeep.cloud/app` = sign-in wall, tanpa sesi/kredensial |

Lihat `docs/DEPLOY.md` untuk urutan deploy dan bukti yang harus dikumpulkan.

