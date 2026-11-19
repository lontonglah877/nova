#!/usr/bin/env python3
"""NOVA cron helper: nightly backup, silent unless something is wrong.

Runs under `hermes cron create --no-agent --script nova_backup.py ...`.
Empty stdout means "no notification" — Hermes only pings on failure.
"""

import os
import sys

NOVA_ROOT = os.environ.get("NOVA_ROOT", os.path.expanduser("~/nova"))
sys.path.insert(0, os.path.join(NOVA_ROOT, "app"))


def main() -> int:
    from nova import db
    from nova.services import backup

    conn = None
    try:
        conn = db.open_db()
        result = backup.run_backup(conn, {"keep": 7})
        print(result["path"])  # kept for the cron run history, not a notification
        return 0
    except Exception as exc:  # noqa: BLE001 - any failure must reach the human
        print(f"NOVA backup GAGAL: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
