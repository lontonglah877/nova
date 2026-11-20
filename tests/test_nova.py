"""NOVA acceptance tests. Each test uses its own temp database and NOVA_HOME."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from nova import db as nova_db
from nova.services import backup, documents, learning, life, monitoring, projects, trading
from nova.util import iso, now_utc


class NovaCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nova-test-"))
        os.environ["NOVA_HOME"] = str(self.tmp)
        os.environ["NOVA_DB"] = str(self.tmp / "data" / "nova.sqlite")
        os.environ["NOVA_BACKUP_DIR"] = str(self.tmp / "backups")
        os.environ["NOVA_WORKSPACE"] = str(self.tmp / "workspace")
        self.conn = nova_db.open_db(self.tmp / "data" / "nova.sqlite")

    def tearDown(self):
        try:
            self.conn.close()
        finally:
            for key in ("NOVA_HOME", "NOVA_DB", "NOVA_BACKUP_DIR", "NOVA_WORKSPACE"):
                os.environ.pop(key, None)
            shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, stdin_text: str | None = None):
        env = dict(os.environ)
        res = subprocess.run(
            [sys.executable, str(ROOT / "app" / "nova" / "cli.py"), *args],
            capture_output=True, text=True, env=env, timeout=120, input=stdin_text,
        )
        return res.returncode, res.stdout


class TestMigration(NovaCase):
    def test_schema_and_version(self):
        version = self.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        self.assertEqual(version, 1)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for required in ("inbox_items", "notes", "tasks", "goals", "goal_milestones",
                         "reminders", "projects", "project_tasks", "documents",
                         "document_tags", "study_topics", "flashcards", "study_attempts",
                         "study_reviews", "market_watchlist", "market_snapshots",
                         "trading_signals", "trading_journal", "notifications", "decisions",
                         "system_events", "backup_history"):
            self.assertIn(required, tables, f"missing table {required}")

    def test_migrate_is_idempotent(self):
        second = nova_db.migrate(self.conn)
        self.assertEqual(second, [], "migrate must not re-apply completed versions")

    def test_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO goal_milestones (id,goal_id,title,status,weight,created_at) "
                "VALUES ('x','nonexistent','t','open',1.0,?)", (iso(),))


class TestInbox(NovaCase):
    def test_create_list_update_promote(self):
        iid = life.inbox_add(self.conn, {"title": "Ide proyek NOVA", "kind": "idea"})["id"]
        listed = life.inbox_list(self.conn, {})
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["status"], "new")
        life.inbox_update(self.conn, {"id": iid, "category": "proyek"})
        row = self.conn.execute("SELECT category FROM inbox_items WHERE id=?", (iid,)).fetchone()
        self.assertEqual(row["category"], "proyek")
        promoted = life.inbox_promote(self.conn, {"id": iid, "to": "task"})
        task = self.conn.execute("SELECT title FROM tasks WHERE id=?",
                                 (promoted["created_id"],)).fetchone()
        self.assertEqual(task["title"], "Ide proyek NOVA")
        status = self.conn.execute("SELECT status FROM inbox_items WHERE id=?", (iid,)).fetchone()
        self.assertEqual(status["status"], "promoted")

    def test_update_missing_raises(self):
        with self.assertRaises(LookupError):
            life.inbox_update(self.conn, {"id": "inb_missing", "category": "x"})


class TestTasks(NovaCase):
    def test_dedupe_by_idempotency_key(self):
        first = life.task_add(self.conn, {"title": "Tugas A", "idempotency_key": "k1"})
        second = life.task_add(self.conn, {"title": "Tugas A", "idempotency_key": "k1"})
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["id"], second["id"])
        count = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, 1)

    def test_complete_is_idempotent(self):
        tid = life.task_add(self.conn, {"title": "Tugas B"})["id"]
        self.assertFalse(life.task_complete(self.conn, {"id": tid})["already_done"])
        self.assertTrue(life.task_complete(self.conn, {"id": tid})["already_done"])
        row = self.conn.execute("SELECT status, completed_at FROM tasks WHERE id=?", (tid,)).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertIsNotNone(row["completed_at"])

    def test_reschedule_reopens_and_sets_utc(self):
        tid = life.task_add(self.conn, {"title": "Tugas C"})["id"]
        life.task_complete(self.conn, {"id": tid})
        res = life.task_reschedule(self.conn, {"id": tid, "due_at": "2026-11-20T09:00:00+07:00"})
        row = self.conn.execute("SELECT status, due_at FROM tasks WHERE id=?", (tid,)).fetchone()
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["due_at"], "2026-11-20T02:00:00Z")
        self.assertEqual(res["due"], "2026-11-20 09:00 WIB")

    def test_invalid_priority_rejected(self):
        with self.assertRaises(ValueError):
            life.task_add(self.conn, {"title": "x", "priority": 9})

    def test_archive(self):
        tid = life.task_add(self.conn, {"title": "Tugas D"})["id"]
        life.task_archive(self.conn, {"id": tid})
        active = life.task_list(self.conn, {"status": "active"})["count"]
        self.assertEqual(active, 0)


class TestGoals(NovaCase):
    def test_weighted_progress(self):
        gid = life.goal_add(self.conn, {
            "title": "Lulus semester 5",
            "milestones": [{"title": "M1", "weight": 2}, {"title": "M2", "weight": 2}],
        })["id"]
        mids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM goal_milestones WHERE goal_id=?", (gid,))]
        life.goal_milestone_done(self.conn, {"id": mids[0]})
        prog = life.goal_progress(self.conn, gid)
        self.assertEqual(prog["percent"], 50.0)
        life.goal_milestone_done(self.conn, {"id": mids[1]})
        self.assertEqual(life.goal_progress(self.conn, gid)["percent"], 100.0)

    def test_weighted_not_count_based(self):
        gid = life.goal_add(self.conn, {
            "title": "G",
            "milestones": [{"title": "big", "weight": 9}, {"title": "small", "weight": 1}],
        })["id"]
        small = self.conn.execute(
            "SELECT id FROM goal_milestones WHERE goal_id=? AND weight=1", (gid,)).fetchone()["id"]
        life.goal_milestone_done(self.conn, {"id": small})
        self.assertEqual(life.goal_progress(self.conn, gid)["percent"], 10.0)


class TestReminders(NovaCase):
    def test_add_dedupe_cancel(self):
        due = (now_utc() + timedelta(hours=1)).isoformat()
        r1 = life.reminder_add(self.conn, {"title": "Minum obat", "due_at": due,
                                           "dedupe_key": "obat-1"})
        r2 = life.reminder_add(self.conn, {"title": "Minum obat", "due_at": due,
                                           "dedupe_key": "obat-1"})
        self.assertTrue(r2["deduplicated"])
        self.assertEqual(r1["id"], r2["id"])
        life.reminder_cancel(self.conn, {"id": r1["id"]})
        row = self.conn.execute("SELECT status FROM reminders WHERE id=?", (r1["id"],)).fetchone()
        self.assertEqual(row["status"], "cancelled")
        # a cancelled reminder frees its dedupe key so the user can reuse it
        # (row is reset rather than duplicated, because dedupe_key is UNIQUE)
        again = life.reminder_add(self.conn, {"title": "Minum obat", "due_at": due,
                                              "dedupe_key": "obat-1"})
        self.assertEqual(again["id"], r1["id"])
        self.assertTrue(again["reused"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM reminders").fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM reminders WHERE id=?", (r1["id"],)).fetchone()["status"], "pending")

    def test_past_due_rejected(self):
        with self.assertRaises(ValueError):
            life.reminder_add(self.conn, {"title": "x", "due_at": "2020-01-01T00:00:00Z"})

    def test_snooze_moves_target(self):
        rid = life.reminder_add(self.conn, {
            "title": "Telepon", "due_at": (now_utc() + timedelta(minutes=5)).isoformat()})["id"]
        life.reminder_snooze(self.conn, {"id": rid, "minutes": 30})
        row = self.conn.execute("SELECT status, snoozed_until FROM reminders WHERE id=?",
                                (rid,)).fetchone()
        self.assertEqual(row["status"], "snoozed")
        self.assertIsNotNone(row["snoozed_until"])

    def test_due_uses_snooze_or_due(self):
        rid = life.reminder_add(self.conn, {
            "title": "Due test", "due_at": (now_utc() + timedelta(hours=2)).isoformat()})["id"]
        self.assertEqual(life.reminder_due(self.conn, {})["count"], 0)
        self.conn.execute("UPDATE reminders SET due_at=? WHERE id=?",
                          (iso(now_utc() - timedelta(minutes=1)), rid))
        self.assertEqual(life.reminder_due(self.conn, {})["count"], 1)

    def test_timezone_conversion(self):
        # a future instant expressed in +07:00 must round-trip to the same WIB wall clock
        local = (now_utc() + timedelta(hours=2)).astimezone(timezone(timedelta(hours=7)))
        stamp = local.replace(microsecond=0).isoformat()
        res = life.reminder_add(self.conn, {"title": "tz", "due_at": stamp})
        self.assertTrue(res["due"].startswith(local.strftime("%Y-%m-%d %H:%M")))


class TestLearning(NovaCase):
    def test_card_due_and_review_schedule(self):
        tid = learning.topic_add(self.conn, {"name": "Kolangitis"})["id"]
        cid = learning.card_add(self.conn, {"topic_id": tid, "front": "Trias Charcot?",
                                            "back": "Demam, nyeri RUQ, ikterus"})["id"]
        self.assertEqual(learning.card_due(self.conn, {})["count"], 1)
        first = learning.card_review(self.conn, {"id": cid, "grade": "good"})
        self.assertEqual(first["interval_days"], 1)
        self.assertEqual(learning.card_due(self.conn, {})["count"], 0)
        attempt = self.conn.execute(
            "SELECT correct FROM study_attempts WHERE flashcard_id=?", (cid,)).fetchone()
        self.assertEqual(attempt["correct"], 1)

    def test_again_resets_and_lapses(self):
        cid = learning.card_add(self.conn, {"front": "q", "back": "a"})["id"]
        learning.card_review(self.conn, {"id": cid, "grade": "good"})
        res = learning.card_review(self.conn, {"id": cid, "grade": "again"})
        row = self.conn.execute("SELECT reps, lapses, ease FROM flashcards WHERE id=?",
                                (cid,)).fetchone()
        self.assertEqual(row["reps"], 0)
        self.assertEqual(row["lapses"], 1)
        self.assertLessEqual(row["ease"], 2.5)
        self.assertEqual(res["interval_days"], 0)

    def test_invalid_grade_rejected(self):
        cid = learning.card_add(self.conn, {"front": "q", "back": "a"})["id"]
        with self.assertRaises(ValueError):
            learning.card_review(self.conn, {"id": cid, "grade": "perfect"})

    def test_progress_reports_real_counts(self):
        tid = learning.topic_add(self.conn, {"name": "Kolelitiasis"})["id"]
        learning.card_add(self.conn, {"topic_id": tid, "front": "f", "back": "b"})
        learning.attempt_add(self.conn, {"topic_id": tid, "correct": False, "mode": "quiz"})
        p = learning.progress(self.conn, {})
        self.assertEqual(p["cards_total"], 1)
        self.assertEqual(p["attempts_7d"], 1)
        self.assertEqual(p["accuracy_7d"], 0.0)
        self.assertEqual(p["weak_topics"][0]["topic"], "Kolelitiasis")


class TestTrading(NovaCase):
    def test_snapshot_requires_provenance(self):
        with self.assertRaises(ValueError):
            trading.snapshot_add(self.conn, {"symbol": "BTC", "price": 100})
        with self.assertRaises(ValueError):
            trading.snapshot_add(self.conn, {"symbol": "BTC", "price": 100,
                                             "source": "x", "observed_at": "not-a-date"})

    def test_snapshot_dedupe_and_stale_flag(self):
        trading.snapshot_add(self.conn, {"symbol": "BTC", "venue": "spot", "price": 65000,
                                         "source": "fixture", "observed_at": iso()})
        trading.snapshot_add(self.conn, {"symbol": "BTC", "venue": "spot", "price": 65000,
                                         "source": "fixture", "observed_at": iso()})
        n = self.conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        self.assertEqual(n, 1, "same symbol/venue/time/source must not duplicate")
        trading.watch_add(self.conn, {"symbol": "btc", "venue": "spot"})
        row = trading.watch_list(self.conn, {})["watchlist"][0]
        self.assertEqual(row["symbol"], "BTC")
        self.assertFalse(row["stale"])

    def test_import_csv_rejects_bad_rows(self):
        csv_text = ("symbol,price,source,observed_at,venue\n"
                    "ETH,3200,fixture,2026-11-18T10:00:00Z,spot\n"
                    "SOL,,fixture,2026-11-18T10:00:00Z,spot\n")
        res = trading.import_snapshots(self.conn, {"content": csv_text, "format": "csv"})
        self.assertEqual(res["accepted"], 1)
        self.assertEqual(len(res["rejected"]), 1)
        self.assertIn("price", res["rejected"][0]["reason"])

    def test_signal_validation(self):
        with self.assertRaises(ValueError):
            trading.signal_add(self.conn, {"symbol": "BTC", "side": "buy", "source": "x",
                                           "observed_at": iso()})
        res = trading.signal_add(self.conn, {"symbol": "btc", "side": "long",
                                             "source": "fixture", "observed_at": iso(),
                                             "confidence": 0.6, "rationale": "fixture data"})
        self.assertEqual(res["side"], "long")
        self.assertIn("bukan rekomendasi", res["disclaimer"])

    def test_no_order_execution_api(self):
        names = {n for n in dir(trading) if not n.startswith("_")}
        for forbidden in ("order", "execute", "withdraw", "submit_order", "place_order"):
            self.assertNotIn(forbidden, names,
                             f"trading must stay read-only, found {forbidden}")

    def test_performance_needs_closed_trades(self):
        res = trading.performance(self.conn, {})
        self.assertEqual(res["status"], "no_data")
        tid = trading.journal_add(self.conn, {"symbol": "BTC", "side": "long",
                                              "entry_price": 100, "stop_loss": 90,
                                              "opened_at": iso()})["id"]
        trading.journal_close(self.conn, {"id": tid, "exit_price": 120})
        perf = trading.performance(self.conn, {})
        self.assertEqual(perf["trades"], 1)
        self.assertEqual(perf["avg_r"], 2.0)
        self.assertEqual(perf["win_rate"], 1.0)


class TestDocuments(NovaCase):
    def test_unsupported_type(self):
        p = self.tmp / "x.exe"
        p.write_bytes(b"\x00\x01")
        res = documents.intake(self.conn, {"path": str(p)})
        self.assertEqual(res["status"], "unsupported")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM documents WHERE status='unsupported'").fetchone()[0], 1)

    def test_oversize_rejected(self):
        p = self.tmp / "big.txt"
        p.write_text("x" * (documents.MAX_BYTES + 10))
        res = documents.intake(self.conn, {"path": str(p)})
        self.assertEqual(res["status"], "oversize")
        self.assertIsNone(res["stored_path"])

    def test_text_extraction_and_tags(self):
        p = self.tmp / "note.md"
        p.write_text("# Catatan\nKolangitis = infeksi duktus biliaris.")
        res = documents.intake(self.conn, {"path": str(p), "tags": ["medis"]})
        self.assertEqual(res["status"], "extracted")
        self.assertGreater(res["extracted_chars"], 0)
        self.assertEqual(res["trust"], "untrusted_data")
        got = documents.get_document(self.conn, {"id": res["id"]})
        self.assertIn("Kolangitis", got["excerpt"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM document_tags").fetchone()[0], 1)

    def test_missing_file(self):
        with self.assertRaises(LookupError):
            documents.intake(self.conn, {"path": str(self.tmp / "nope.pdf")})


class TestProjects(NovaCase):
    def test_workspace_escape_blocked(self):
        with self.assertRaises(ValueError):
            projects.project_add(self.conn, {"name": "evil", "workspace": "../../etc"})

    def test_project_and_tasks(self):
        res = projects.project_add(self.conn, {"name": "NOVA Bot", "objective": "WA assistant"})
        self.assertTrue(Path(res["workspace"]).exists())
        tid = projects.ptask_add(self.conn, {"project_id": res["id"], "title": "Pairing"})["id"]
        projects.ptask_update(self.conn, {"id": tid, "status": "done"})
        p = projects.project_list(self.conn, {})["projects"][0]
        self.assertEqual(p["tasks_done"], 1)
        with self.assertRaises(ValueError):
            projects.ptask_update(self.conn, {"id": tid, "status": "finished"})

    def test_decision_log(self):
        did = projects.decision_log(self.conn, {"log": True, "title": "Pakai SQLite",
                                                "decision": "Pakai SQLite, bukan Postgres"})["id"]
        rows = projects.decision_log(self.conn, {})["decisions"]
        self.assertEqual(rows[0]["title"], "Pakai SQLite")


class TestBackup(NovaCase):
    def test_backup_and_restore_test(self):
        life.task_add(self.conn, {"title": "Sebelum backup"})
        res = backup.run_backup(self.conn, {})
        self.assertTrue(Path(res["path"]).exists())
        self.assertEqual(res["verified_schema_version"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM backup_history").fetchone()[0], 1)
        restored = backup.restore_test(self.conn, {"path": res["path"]})
        self.assertEqual(restored["integrity"], "ok")
        self.assertEqual(restored["row_counts"]["tasks"], 1)
        self.assertTrue(restored["production_untouched"])

    def test_prune_keeps_newest(self):
        for _ in range(3):
            backup.run_backup(self.conn, {"keep": 2})
        kept = backup.list_backups(self.conn, {})["count"]
        self.assertEqual(kept, 2)


class TestMonitoring(NovaCase):
    def test_check_reports_real_state(self):
        res = monitoring.check(self.conn, {})
        self.assertIn(res["status"], ("ok", "degraded"))
        self.assertEqual(res["db"]["integrity"], "ok")
        self.assertFalse(res["integrations"]["trading_execution"]["enabled"])
        self.assertIsNotNone(res["disk"].get("free_bytes"))

    def test_watchdog_silent_when_healthy(self):
        res = monitoring.watchdog(self.conn, {})
        self.assertEqual(res["should_notify"], any(
            a["level"] == "error" for a in res["alerts"]))

    def test_integration_status_never_leaks_values(self):
        os.environ["OPENAI_API_KEY"] = "sk-secret-value-should-not-appear"
        res = monitoring.integrations_status()
        dumped = json.dumps(res)
        self.assertNotIn("sk-secret-value-should-not-appear", dumped)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_event_log(self):
        eid = monitoring.log_event(self.conn, {"kind": "test", "message": "ok"})["id"]
        with self.assertRaises(ValueError):
            monitoring.log_event(self.conn, {"kind": "test", "message": "x", "severity": "panic"})
        self.assertEqual(monitoring.events_list(self.conn, {})["count"], 1)


class TestCLI(NovaCase):
    def test_unknown_command_exits_2(self):
        code, out = self.cli("task", "bogus")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_validation_error_exits_2(self):
        code, out = self.cli("task", "add", "--args", '{"title": ""}')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "validation_error")

    def test_not_found_exits_3(self):
        code, out = self.cli("task", "complete", "--args", '{"id": "task_missing"}')
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "not_found")

    def test_success_is_json_ok(self):
        code, out = self.cli("task", "add", "--args", '{"title":"cli task"}')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_stdin_payload(self):
        code, out = self.cli("task", "add", stdin_text='{"title":"from stdin"}')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])
        row = self.conn.execute("SELECT title FROM tasks WHERE title='from stdin'").fetchone()
        self.assertIsNotNone(row, "stdin payload must actually reach the service layer")

    def test_alias_forms_resolve(self):
        self.assertEqual(self.cli("inbox", "capture", "--args", '{"title":"alias"}')[0], 0)
        self.assertEqual(self.cli("study", "card.add", "--args",
                                  '{"front":"f","back":"b"}')[0], 0)

    def test_invalid_json_payload(self):
        code, out = self.cli("task", "add", "--args", "{not json}")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "validation_error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
