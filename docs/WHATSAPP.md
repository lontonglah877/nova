# NOVA — WhatsApp

## Mode yang dipakai: `bot` (nomor khusus)

Nomor bot terpisah dari nomor pribadi. Pesan dari nomor lain masuk ke agen; balasan dikirim
dari nomor bot.

Nomor bot **belum final**. Jangan menuliskan nomor apa pun ke konfigurasi sebelum pemilik
mengonfirmasi.

## Langkah saat nomor sudah ada

Jalankan wizard WhatsApp untuk profil nova (interaktif, butuh terminal):

```bash
hermes -p nova whatsapp
```

Wizard menanyakan tiga hal:

1. **Mode** → pilih `1` (separate bot number).
2. **Nomor yang boleh menghubungi bot** → nomor pemilik, format kode negara tanpa `+`
   (contoh `628xxxxxxxxxx`). Nilai ini mengisi `WHATSAPP_ALLOWED_USERS`.
3. **QR** muncul di terminal → buka WhatsApp pada ponsel **nomor bot** →
   Settings → Linked Devices → Link a Device → pindai.

Wizard hanya menulis `WHATSAPP_ENABLED=true` setelah `creds.json` benar-benar ada. Kalau QR
tidak dipindai, WhatsApp tetap nonaktif — sehingga tidak ada gateway yang menunggu bridge kosong.

## Setelah pairing

Gateway host saat ini sudah melayani profil `default` dan `nova` dalam satu proses
(lihat `hermes gateway list`). Profil baru jadi aktif pada gateway itu setelah gateway host
dimuat ulang; lakukan dari shell di luar Hermes, bukan dari dalam sesi agen:

- hentikan lalu jalankan kembali layanan gateway host lewat Windows Startup item
  `Hermes_Gateway.vbs`, **atau**
- pakai `hermes gateway` subcommand lifecycle dari Command Prompt/Terminal terpisah.

Jangan pernah menjalankan `hermes gateway run` kedua untuk profil yang sama: dua gateway pada
satu Hermes home akan saling menimpa `gateway.pid`, `state.db`, dan sesi.

Verifikasi:

```bash
hermes gateway list          # profil & PID yang dilayani
hermes -p nova gateway status
```

Lalu kirim pesan dari nomor pemilik ke nomor bot. Balasan pertama adalah bukti hidup.

## Risiko yang harus diketahui

- Bridge memakai Baileys (WhatsApp Web), bukan API resmi. WhatsApp dapat menutup nomor yang
  dianggap otomatis. Pakai nomor khusus, jangan broadcast, jangan kirim massal.
- Nomor bot harus bisa menerima OTP SMS/telepon saat pendaftaran WhatsApp.
- Jangan pasang nomor bot di dua perangkat secara bersamaan.
- Kebijakan grup: biarkan `pairing`/`allowlist`. Jangan `open` — bot akan menjawab siapa pun.
- `WHATSAPP_DM_POLICY` default `pairing`; dengan `WHATSAPP_ALLOWED_USERS` terisi, allowlist
  mematikan pairing terbuka sehingga hanya nomor pemilik yang dilayani.
