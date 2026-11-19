"""NOVA CLI. Deterministic JSON in, JSON out. Called by Hermes terminal tool.

    nova <domain> <action> [--args '{json}']     # JSON on stdout
    nova db init | health | version | commands

Exit codes: 0 ok, 2 validation error, 3 not found, 1 unexpected failure.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova import __version__
from nova.db import db_path, open_db
from nova.services import backup, documents, learning, life, monitoring, projects, trading
from nova.util import emit, fail, ok, read_payload

COMMAND_TABLE = {
    "inbox": (life.inbox_add, life.inbox_list, life.inbox_update, life.inbox_promote),
    "task": (life.task_add, life.task_list, life.task_update, life.task_complete,
             life.task_reschedule, life.task_archive),
    "goal": (life.goal_add, life.goal_list, life._goal_status,
             life.goal_milestone_add, life.goal_milestone_done),
    "reminder": (life.reminder_add, life.reminder_list, life.reminder_cancel,
                 life.reminder_snooze, life.reminder_due, life.reminder_mark_sent),
    "note": (life.notes_add, life.notes_search),
    "review": (life.daily_review, life.weekly_review),
    "study": (learning.topic_add, learning.topic_list, learning.card_add, learning.card_due,
              learning.card_review, learning.attempt_add, learning.progress, learning.review_due),
    "market": (trading.watch_add, trading.watch_list, trading.snapshot_add,
               trading.import_snapshots, trading.signal_add, trading.price_alerts_due),
    "journal": (trading.journal_add, trading.journal_close, trading.journal_list),
    "performance": (trading.performance,),
    "document": (documents.intake, documents.list_documents, documents.get_document,
                 documents.set_summary, documents.tag_add),
    "project": (projects.project_add, projects.project_list, projects.ptask_add,
                projects.ptask_update, projects.decision_log, projects.file_index),
    "backup": (backup.run_backup, backup.list_backups, backup.restore_test),
    "system": (monitoring.check, monitoring.watchdog, monitoring.log_event,
               monitoring.events_list),
}

# Order matters for prefix matching; longer names first.
_ACTION_NAMES = {
    life.inbox_add: ["add", "capture"],
    life.inbox_list: ["list"],
    life.inbox_update: ["update"],
    life.inbox_promote: ["promote"],
    life.task_add: ["add", "create"],
    life.task_list: ["list"],
    life.task_update: ["update"],
    life.task_complete: ["complete", "done"],
    life.task_reschedule: ["reschedule"],
    life.task_archive: ["archive"],
    life.goal_add: ["add"],
    life.goal_list: ["list"],
    life._goal_status: ["status"],
    life.goal_milestone_add: ["milestone-add", "milestone.add"],
    life.goal_milestone_done: ["milestone-done", "milestone.done"],
    life.reminder_add: ["add"],
    life.reminder_list: ["list"],
    life.reminder_cancel: ["cancel"],
    life.reminder_snooze: ["snooze"],
    life.reminder_due: ["due"],
    life.reminder_mark_sent: ["mark-sent", "mark_sent"],
    life.notes_add: ["add"],
    life.notes_search: ["search", "list"],
    life.daily_review: ["daily"],
    life.weekly_review: ["weekly"],
    learning.topic_add: ["topic-add", "topic.add"],
    learning.topic_list: ["topic-list", "topics", "topic.list"],
    learning.card_add: ["card-add", "card.add"],
    learning.card_due: ["card-due", "due", "card.due"],
    learning.card_review: ["card-review", "review", "card.review"],
    learning.attempt_add: ["attempt-add", "attempt", "attempt.add"],
    learning.progress: ["progress"],
    learning.review_due: ["review-due", "reviews", "review.due"],
    trading.watch_add: ["watch-add", "watch", "watch.add"],
    trading.watch_list: ["watch-list", "watchlist", "watch.list"],
    trading.snapshot_add: ["snapshot-add", "snapshot", "snapshot.add"],
    trading.import_snapshots: ["import", "import-snapshots", "import.snapshots"],
    trading.signal_add: ["signal-add", "signal", "signal.add"],
    trading.price_alerts_due: ["alerts-due", "alerts", "alerts.due"],
    trading.journal_add: ["add"],
    trading.journal_close: ["close"],
    trading.journal_list: ["list"],
    trading.performance: ["show", "report", "performance", "list"],
    documents.intake: ["intake", "add"],
    documents.list_documents: ["list"],
    documents.get_document: ["get", "show"],
    documents.set_summary: ["summary", "set-summary"],
    documents.tag_add: ["tag-add", "tag", "tag.add"],
    projects.project_add: ["add"],
    projects.project_list: ["list"],
    projects.ptask_add: ["task-add", "task.add"],
    projects.ptask_update: ["task-update", "task.update"],
    projects.decision_log: ["decision"],
    projects.file_index: ["files"],
    backup.run_backup: ["run", "create"],
    backup.list_backups: ["list"],
    backup.restore_test: ["restore-test", "restore.test"],
    monitoring.check: ["check", "status"],
    monitoring.watchdog: ["watchdog"],
    monitoring.log_event: ["event-log", "event.log"],
    monitoring.events_list: ["events", "event-list", "event.list"],
}


def list_commands() -> dict:
    out = {}
    for domain, funcs in COMMAND_TABLE.items():
        names = []
        for fn in funcs:
            names.append(_ACTION_NAMES[fn][0].replace("-", ""))
        out[domain] = names
    return out


def resolve(domain: str, action: str):
    funcs = COMMAND_TABLE.get(domain)
    if not funcs:
        return None
    wanted = action.replace("_", "-").lower()
    for fn in funcs:
        for name in _ACTION_NAMES[fn]:
            if name.replace("_", "-").lower() == wanted:
                return fn
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova", description="NOVA personal assistant CLI")
    parser.add_argument("domain", nargs="?", help="inbox|task|goal|reminder|note|review|study|market|"
                                                  "journal|performance|document|project|backup|system")
    parser.add_argument("action", nargs="?")
    parser.add_argument("--args", dest="payload", default=None, help="JSON payload")
    parser.add_argument("--db", default=None, help="override database path")
    args = parser.parse_args(argv)

    domain = (args.domain or "").strip().lower()
    action = (args.action or "").strip().lower()

    try:
        if domain in ("", "commands", "help"):
            emit(ok({"version": __version__, "domains": list_commands(),
                     "db": str(db_path())}))
            return 0
        if domain == "version":
            emit(ok({"version": __version__, "python": sys.version.split()[0]}))
            return 0
        if domain == "db":
            conn = open_db(Path(args.db) if args.db else None)
            if action in ("init", "migrate"):
                emit(ok({"db": str(conn.execute("PRAGMA database_list").fetchone()[2]),
                         "schema_version": conn.execute(
                             "SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                         "open_db_created": True}))
                return 0
            emit(fail("bad_request", f"unknown db action: {action}"), 2)
            return 2
        if domain == "health":
            conn = open_db(Path(args.db) if args.db else None)
            emit(ok(monitoring.check(conn, {})))
            return 0

        func = resolve(domain, action)
        if not func:
            emit(fail("bad_request", f"unknown command: {domain} {action}. "
                                    f"Run 'nova commands' for the list."), 2)
            return 2
        payload = read_payload(args.payload)
        conn = open_db(Path(args.db) if args.db else None)
        try:
            result = func(conn, payload)
        finally:
            conn.close()
        emit(ok(result))
        return 0
    except ValueError as exc:
        emit(fail("validation_error", str(exc)), 2)
        return 2
    except LookupError as exc:
        emit(fail("not_found", str(exc)), 3)
        return 3
    except Exception as exc:  # noqa: BLE001 - JSON error, never a stack trace to the chat
        emit(fail("internal_error", f"{type(exc).__name__}: {exc}",
                  trace=traceback.format_exc().splitlines()[-3:]), 1)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
