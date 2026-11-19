# NOVA — Arsitektur

## Bentuk sistem

```
WhatsApp (nomor bot)
   ↓  Baileys bridge (Node)
Hermes Gateway  →  profil `nova`  →  agen utama + Skills
   ↓
nx CLI  →  app/nova/services/*.py  →  data/nova.sqlite
```

Satu gateway, satu profil, satu agen. Kemampuan tambahan datang dari **Skills**, bukan dari
gateway tambahan. Dua gateway dengan Hermes home yang sama akan saling menimpa state — dilarang.

## Lapisan

| Lapisan | Berkas | Tanggung jawab |
|---|---|---|
| Transport | Baileys bridge (`scripts/whatsapp-bridge`) | QR pairing, kirim/terima pesan |
| Bahasa | profil `nova` + `skills/nova/SKILL.md` | memahami pesan, memilih aksi, menulis balasan |
| Data | `app/nova/cli.py`, `app/nova/services/*.py` | validasi, transaksi, idempotensi |
| Simpan | `app/nova/db.py` + `data/nova.sqlite` | skema berversi, migrasi append-only |

## Mengapa CLI, bukan SQL langsung

Agen harus punya satu permukaan yang stabil. `nx` memvalidasi input, mengubah waktu ke UTC,
menjaga idempotensi, dan mengembalikan JSON yang seragam. SQL bebas dari agen akan merusak
invarian dalam hitungan hari.

## Invarian

1. **Semua waktu disimpan UTC**, ditampilkan WIB (UTC+7). Input tanpa offset ditolak.
2. **Idempotensi**: operasi tulis menerima kunci; kirim ulang tidak menggandakan baris.
3. **Provenance**: snapshot pasar dan sinyal wajib punya `source` + `observed_at`.
4. **Read-only trading**: tidak ada modul yang bisa membuat order.
5. **Migrasi append-only**: versi yang sudah dirilis tidak boleh diedit.
6. **DB NOVA terpisah** dari `~/.hermes/state.db`.

## Ketahanan

- `system check` — integritas DB, ruang disk, status integrasi (tanpa membocorkan nilai rahasia).
- `system watchdog` — hanya berbunyi bila ada masalah; dipakai cron untuk alarm.
- `backup run` — SQLite online-backup API (snapshot konsisten) + sha256.
- `backup restoretest` — memulihkan ke file sementara dan menghitung baris; produksi tidak disentuh.
