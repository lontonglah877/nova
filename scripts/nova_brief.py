#!/usr/bin/env python3
"""NOVA cron helper: print the daily state as compact JSON for the agent prompt.

Invoked by `hermes cron create --script nova_brief.py ...` (script mode: stdout is
injected into the agent's prompt). Read-only: it never mutates the database.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

NOVA_ROOT = os.environ.get("NOVA_ROOT", os.path.expanduser("~/nova"))
sys.path.insert(0, os.path.join(NOVA_ROOT, "app"))

WIB = timezone(timedelta(hours=7))


def db_path() -> str:
    env = os.environ.get("NOVA_DB")
    if env:
        return env
    home = os.environ.get("NOVA_HOME") or os.path.expanduser("~/nova")
    return os.path.join(home, "data", "nova.sqlite")


def main() -> int:
    path = db_path()
    if not os.path.exists(path):
        print(json.dumps({"status": "no_db", "path": path}))
        return 0
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    today = datetime.now(WIB).strftime("%Y-%m-%d")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a).fetchall()]
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date_wib": today,
        "tasks_due_24h": q(
            "SELECT id,title,priority,due_at FROM tasks "
            "WHERE status IN ('open','doing') AND due_at IS NOT NULL AND due_at <= ? "
            "ORDER BY due_at LIMIT 20", soon),
        "tasks_overdue": q(
            "SELECT id,title,due_at FROM tasks "
            "WHERE status IN ('open','doing') AND due_at IS NOT NULL AND due_at < ? "
            "ORDER BY due_at LIMIT 20", now.strftime("%Y-%m-%dT%H:%M:%S")),
        "reminders_due": q(
            "SELECT id,title,COALESCE(snoozed_until,due_at) AS at FROM reminders "
            "WHERE status IN ('pending','snoozed') "
            "AND COALESCE(snoozed_until,due_at) <= ? ORDER BY at LIMIT 20",
            now.strftime("%Y-%m-%dT%H:%M:%S")),
        "inbox_new": q(
            "SELECT title FROM inbox_items WHERE status='new' ORDER BY created_at DESC LIMIT 10"),
        "cards_due": q(
            "SELECT COUNT(*) AS n FROM flashcards WHERE due_at IS NOT NULL AND due_at <= ?",
            now.strftime("%Y-%m-%dT%H:%M:%S"))[0]["n"],
        "open_goals": q(
            "SELECT title,status FROM goals WHERE status NOT IN ('done','dropped') LIMIT 10"),
    }
    conn.close()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
