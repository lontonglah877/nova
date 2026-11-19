"""Health checks: DB, disk, memory, process/service, integration status. Real data only."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from ..db import tx as _tx
from ..util import display_ts, iso, new_id, require as _require, to_int

DISK_WARN_PCT = 85
DISK_CRIT_PCT = 95
RAM_WARN_PCT = 85


def _meminfo() -> dict:
    if sys.platform.startswith("linux"):
        data = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, _, rest = line.partition(":")
                data[key] = int(rest.strip().split()[0]) * 1024
        except (OSError, ValueError):
            return {}
        total = data.get("MemTotal", 0)
        avail = data.get("MemAvailable", data.get("MemFree", 0))
        return {"total_bytes": total, "available_bytes": avail,
                "used_pct": round(100 * (1 - avail / total), 1) if total else None}
    return {}


def _service_state() -> dict:
    if not shutil.which("systemctl"):
        return {"supported": False, "state": "systemd-not-present"}
    try:
        out = subprocess.run(
            ["systemctl", "is-active", "hermes-gateway"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = "unknown"
    return {"supported": True, "state": out or "unknown"}


def check(conn, payload):
    dbp = Path(os.environ.get("NOVA_DB") or (Path(os.environ.get("NOVA_HOME") or (Path.home() / "nova")) / "data" / "nova.sqlite"))
    alerts = []
    db = {"path": str(dbp), "exists": dbp.exists()}
    if dbp.exists():
        db["size_bytes"] = dbp.stat().st_size
        db["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        db["schema_version"] = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        db["wal_bytes"] = (dbp.parent / (dbp.name + "-wal")).stat().st_size if (dbp.parent / (dbp.name + "-wal")).exists() else 0
    else:
        alerts.append({"level": "error", "what": "database", "detail": "nova.sqlite missing"})

    disk = {}
    try:
        usage = shutil.disk_usage(str(dbp.parent if dbp.parent.exists() else Path.home()))
        pct = round(100 * usage.used / usage.total, 1) if usage.total else None
        disk = {"total_bytes": usage.total, "free_bytes": usage.free, "used_pct": pct}
        if pct is not None and pct >= DISK_CRIT_PCT:
            alerts.append({"level": "error", "what": "disk", "detail": f"used {pct}%"})
        elif pct is not None and pct >= DISK_WARN_PCT:
            alerts.append({"level": "warn", "what": "disk", "detail": f"used {pct}%"})
    except OSError as exc:
        disk = {"error": str(exc)}

    mem = _meminfo()
    if mem.get("used_pct") is not None and mem["used_pct"] >= RAM_WARN_PCT:
        alerts.append({"level": "warn", "what": "ram", "detail": f"used {mem['used_pct']}%"})

    host = {"hostname": socket.gethostname(), "platform": platform.system(),
            "release": platform.release(), "python": platform.python_version()}

    service = _service_state()
    if service["supported"] and service["state"] != "active":
        alerts.append({"level": "warn", "what": "service", "detail": service["state"]})

    counts = {
        "tasks_open": conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('open','doing','blocked')").fetchone()[0],
        "inbox_new": conn.execute("SELECT COUNT(*) FROM inbox_items WHERE status='new'").fetchone()[0],
        "reminders_pending": conn.execute("SELECT COUNT(*) FROM reminders WHERE status='pending'").fetchone()[0],
        "cards_due": conn.execute("SELECT COUNT(*) FROM flashcards WHERE due_at <= ?", (iso(),)).fetchone()[0],
    }

    status = "ok" if not any(a["level"] == "error" for a in alerts) else "degraded"
    return {
        "status": status,
        "checked_at": display_ts(iso()),
        "db": db, "disk": disk, "memory": mem, "host": host,
        "service": service, "counts": counts, "alerts": alerts,
        "integrations": integrations_status(),
    }


def integrations_status() -> dict:
    """Names of configured integrations only — never values."""
    def flag(*names):
        found = [n for n in names if os.environ.get(n)]
        return {"configured": bool(found), "vars": found}

    return {
        "ai_provider": flag("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                            "HERMES_PROVIDER", "DEEPSEEK_API_KEY"),
        "whatsapp": flag("WHATSAPP_ENABLED", "WHATSAPP_ALLOWED_USERS"),
        "atto_cuan": flag("ATTO_CUAN_API_URL", "ATTO_CUAN_API_KEY"),
        "stt": flag("STT_PROVIDER", "DEEPGRAM_API_KEY", "GROQ_API_KEY"),
        "trading_execution": {"enabled": False, "reason": "read-only by design"},
    }


def log_event(conn, payload):
    _require(payload, "kind", "message")
    sev = payload.get("severity") or "info"
    if sev not in ("info", "warn", "error"):
        raise ValueError("severity must be info, warn or error")
    eid = new_id("evt")
    with _tx(conn):
        conn.execute(
            """INSERT INTO system_events (id,kind,severity,message,meta_json,created_at)
               VALUES (?,?,?,?,?,?)""",
            (eid, payload["kind"], sev, payload["message"],
             str(payload.get("meta")) if payload.get("meta") else None, iso()),
        )
    return {"id": eid}


def events_list(conn, payload):
    rows = conn.execute(
        "SELECT * FROM system_events ORDER BY created_at DESC LIMIT ?",
        (to_int(payload.get("limit"), "limit", 20, 1, 200),),
    ).fetchall()
    return {
        "events": [
            {"id": r["id"], "kind": r["kind"], "severity": r["severity"],
             "message": r["message"], "at": display_ts(r["created_at"])}
            for r in rows
        ],
        "count": len(rows),
    }


def watchdog(conn, payload):
    """Cron-friendly: silent (empty alerts) when healthy."""
    result = check(conn, {})
    return {
        "alerts": result["alerts"],
        "should_notify": bool(result["alerts"]),
        "status": result["status"],
        "counts": result["counts"],
        "disk_free_bytes": result["disk"].get("free_bytes"),
        "mem": result["memory"].get("used_pct"),
        "checked_at": result["checked_at"],
    }


ACTIONS = {
    "check": check,
    "watchdog": watchdog,
    "event.log": log_event,
    "event.list": events_list,
}
