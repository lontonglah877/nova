#!/usr/bin/env python3
"""NOVA cron helper: health watchdog. Silent when healthy.

Under `hermes cron create --no-agent --script nova_watchdog.py ...` the stdout IS the
message; empty stdout suppresses the notification entirely.
"""

import os
import sys

NOVA_ROOT = os.environ.get("NOVA_ROOT", os.path.expanduser("~/nova"))
sys.path.insert(0, os.path.join(NOVA_ROOT, "app"))


def main() -> int:
    from nova import db
    from nova.services import monitoring

    conn = None
    try:
        conn = db.open_db()
        result = monitoring.watchdog(conn, {})
    except Exception as exc:  # noqa: BLE001
        print(f"NOVA watchdog tidak bisa memeriksa sistem: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()

    lines = [f"[{a['level']}] {a['message']}" for a in result.get("alerts", [])
             if a.get("level") in ("warn", "error")]
    if lines:
        print("NOVA perlu perhatian:")
        for line in lines:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
