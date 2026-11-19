# NOVA — Referensi perintah

Bentuk: `nx <domain> <action> --args '<json>'`

Exit code: `0` sukses · `2` validasi · `3` tidak ditemukan · `1` error lain.

## inbox
```bash
nx inbox add     --args '{"title":"Ide A","kind":"idea","source":"whatsapp","idempotency_key":"wa-1"}'
nx inbox list    --args '{"status":"new","limit":20}'
nx inbox update  --args '{"id":"inb_...","category":"proyek","status":"triaged"}'
nx inbox promote --args '{"id":"inb_...","to":"task"}'
```
`kind`: idea · task · note · reminder · unknown. `to`: task · note · goal.

## task
```bash
nx task add        --args '{"title":"Baca patofisiologi","priority":2,"due_at":"2026-11-19T21:00:00+07:00"}'
nx task list       --args '{"status":"active"}'
nx task update     --args '{"id":"task_...","priority":1}'
nx task complete   --args '{"id":"task_..."}'
nx task reschedule --args '{"id":"task_...","due_at":"2026-11-20T09:00:00+07:00"}'
nx task archive    --args '{"id":"task_..."}'
```
`status`: open · doing · done · blocked · dropped · archived. `priority` 1–4.

## goal
```bash
nx goal add  --args '{"title":"Lulus semester 5","milestones":[{"title":"Anatomi","weight":3},{"title":"Farmakologi","weight":2}]}'
nx goal list --args '{}'
nx goal status --args '{"id":"goal_..."}'
nx goal milestonedone --args '{"id":"mil_..."}'
```
Progres dihitung dari bobot milestone, bukan jumlahnya.

## reminder
```bash
nx reminder add    --args '{"title":"Minum obat","due_at":"2026-11-19T07:00:00+07:00","dedupe_key":"obat-19"}'
nx reminder list   --args '{"status":"pending"}'
nx reminder snooze --args '{"id":"rem_...","minutes":30}'
nx reminder due    --args '{}'
nx reminder marksent --args '{"id":"rem_..."}'
nx reminder cancel --args '{"id":"rem_..."}'
```
Waktu lampau ditolak. `dedupe_key` unik; pengingat yang dibatalkan bisa dipakai ulang.

## note & review
```bash
nx note add    --args '{"title":"Ringkasan kuliah","body":"...","tags":["medis"]}'
nx note search --args '{"q":"kolangitis"}'
nx review daily  --args '{}'
nx review weekly --args '{}'
```

## study
```bash
nx study topicadd   --args '{"name":"Kolangitis akut"}'
nx study topiclist  --args '{}'
nx study cardadd    --args '{"topic_id":"top_...","front":"Trias Charcot?","back":"Demam, nyeri RUQ, ikterus"}'
nx study carddue    --args '{"limit":10}'
nx study cardreview --args '{"id":"card_...","grade":"good"}'
nx study attemptadd --args '{"topic_id":"top_...","correct":true,"mode":"quiz"}'
nx study progress   --args '{}'
```
`grade`: again(0) · hard(3) · good(4) · easy(5). SM-2: `again` mereset repetisi dan menambah lapse.

## market / journal / performance
```bash
nx market watchadd    --args '{"symbol":"BTC","venue":"spot"}'
nx market watchlist   --args '{}'
nx market snapshotadd --args '{"symbol":"BTC","price":65000,"source":"manual","observed_at":"2026-11-18T10:00:00Z"}'
nx market import      --args '{"content":"symbol,price,source,observed_at,venue\nETH,3200,manual,2026-11-18T10:00:00Z,spot","format":"csv"}'
nx market signaladd   --args '{"symbol":"BTC","side":"long","source":"manual","observed_at":"2026-11-18T10:00:00Z","confidence":0.6,"rationale":"..."}'
nx market alertsdue   --args '{}'
nx journal add        --args '{"symbol":"BTC","side":"long","entry_price":100,"stop_loss":90,"opened_at":"2026-11-18T10:00:00Z"}'
nx journal close      --args '{"id":"jrn_...","exit_price":120}'
nx journal list       --args '{}'
nx performance show   --args '{}'
```
`source` + `observed_at` wajib. Tidak ada perintah order/withdraw — memang tidak dibuat.

## document
```bash
nx document intake  --args '{"path":"/abs/file.pdf","tags":["medis"]}'
nx document list    --args '{}'
nx document get     --args '{"id":"doc_..."}'
nx document summary --args '{"id":"doc_..."}'
nx document tagadd  --args '{"document_id":"doc_...","tag":"jurnal"}'
```
Maks 20 MB. Tipe: txt md csv json log py yaml yml pdf docx html htm.

## project
```bash
nx project add        --args '{"name":"NOVA Bot","objective":"Asisten WA"}'
nx project list       --args '{}'
nx project taskadd    --args '{"project_id":"prj_...","title":"Pairing"}'
nx project taskupdate --args '{"id":"ptsk_...","status":"done"}'
nx project decision   --args '{"log":true,"title":"Pakai SQLite","decision":"SQLite, bukan Postgres"}'
nx project files      --args '{"id":"prj_..."}'
```
Workspace proyek dibatasi di bawah `NOVA_WORKSPACE`; path keluar ditolak.

## backup & system
```bash
nx backup run         --args '{"keep":7}'
nx backup list        --args '{}'
nx backup restoretest --args '{"path":"data/backups/....sqlite"}'
nx system check       --args '{}'
nx system watchdog    --args '{}'
nx system eventlog    --args '{"kind":"deploy","message":"v1 live"}'
nx system events      --args '{"limit":20}'
```

## lain
```bash
nx commands   # daftar domain & aksi dari kode
nx db init    # terapkan migrasi
```
