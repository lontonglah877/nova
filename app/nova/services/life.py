"""Life management: inbox, notes, tasks, goals, milestones, reminders, reviews."""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import timedelta

from ..db import find_by_key, tx
from ..util import display_ts, iso, new_id, now_utc, parse_ts, require, to_int, UTC

TASK_STATUS = ("open", "doing", "done", "blocked", "dropped", "archived")


# --------------------------------------------------------------------------- #
# inbox
# --------------------------------------------------------------------------- #
def inbox_add(conn, payload):
    require(payload, "title")
    title = str(payload["title"]).strip()[:500]
    key = (payload.get("idempotency_key") or "").strip() or None
    if key:
        row = find_by_key(conn, "inbox_items", key)
        if row:
            return {"id": row["id"], "deduplicated": True}
    item_id = new_id("inb")
    with tx(conn):
        conn.execute(
            """INSERT INTO inbox_items
               (id,title,body,kind,category,project_id,source,idempotency_key,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                title,
                (payload.get("body") or None),
                payload.get("kind") or "note",
                payload.get("category"),
                payload.get("project_id"),
                payload.get("source") or "whatsapp",
                key,
                iso(),
                iso(),
            ),
        )
    return {"id": item_id, "deduplicated": False}


def inbox_list(conn, payload):
    status = payload.get("status")
    limit = to_int(payload.get("limit"), "limit", 20, 1, 200)
    sql = "SELECT * FROM inbox_items"
    args: list = []
    if status and status != "all":
        sql += " WHERE status = ?"
        args.append(status)
    elif status != "all":
        sql += " WHERE status IN ('new','classified')"
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return {"items": [_inbox_view(r) for r in rows], "count": len(rows)}


def _inbox_view(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "status": row["status"],
        "category": row["category"],
        "created": display_ts(row["created_at"]),
    }


def inbox_update(conn, payload):
    require(payload, "id")
    allowed = {"status", "category", "body", "kind", "title", "project_id"}
    sets, args = _patch_sets(payload, allowed)
    if not sets:
        raise ValueError("nothing to update")
    sets.append("updated_at = ?")
    args.append(iso())
    args.append(payload["id"])
    with tx(conn):
        cur = conn.execute(f"UPDATE inbox_items SET {', '.join(sets)} WHERE id = ?", args)
    if cur.rowcount == 0:
        raise LookupError(f"inbox item not found: {payload['id']}")
    return {"id": payload["id"], "updated": True}


def inbox_promote(conn, payload):
    """Turn an inbox item into a task (or note) and close the inbox entry."""
    require(payload, "id")
    row = conn.execute("SELECT * FROM inbox_items WHERE id = ?", (payload["id"],)).fetchone()
    if not row:
        raise LookupError(f"inbox item not found: {payload['id']}")
    target = payload.get("to") or "task"
    created_id = None
    with tx(conn):
        if target == "task":
            created_id = _insert_task(
                conn,
                {
                    "title": row["title"],
                    "detail": row["body"],
                    "category": row["category"],
                    "priority": payload.get("priority", 3),
                    "due_at": payload.get("due_at"),
                    "source": "inbox",
                },
            )
        elif target == "note":
            created_id = _insert_note(conn, {"title": row["title"], "body": row["body"]})
        else:
            raise ValueError("to: must be 'task' or 'note'")
        conn.execute(
            "UPDATE inbox_items SET status='promoted', updated_at=? WHERE id=?",
            (iso(), row["id"]),
        )
    return {"inbox_id": row["id"], "created_id": created_id, "to": target}


# --------------------------------------------------------------------------- #
# notes
# --------------------------------------------------------------------------- #
def _insert_note(conn, payload):
    note_id = new_id("note")
    conn.execute(
        """INSERT INTO notes (id,title,body,tags,created_at,updated_at)
           VALUES (?,?,?,?,?,?)""",
        (
            note_id,
            str(payload["title"])[:300],
            payload.get("body"),
            payload.get("tags"),
            iso(),
            iso(),
        ),
    )
    return note_id


def notes_add(conn, payload):
    require(payload, "title")
    with tx(conn):
        note_id = _insert_note(conn, payload)
    return {"id": note_id}


def notes_search(conn, payload):
    q = (payload.get("q") or "").strip()
    limit = to_int(payload.get("limit"), "limit", 20, 1, 100)
    if q:
        like = f"%{q}%"
        rows = conn.execute(
            """SELECT * FROM notes
               WHERE title LIKE ? OR body LIKE ? OR tags LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (like, like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "notes": [
            {
                "id": r["id"],
                "title": r["title"],
                "tags": r["tags"],
                "updated": display_ts(r["updated_at"]),
                "excerpt": (r["body"] or "")[:200],
            }
            for r in rows
        ],
        "count": len(rows),
    }


# --------------------------------------------------------------------------- #
# tasks
# --------------------------------------------------------------------------- #
def _insert_task(conn, payload):
    require(payload, "title")
    key = (payload.get("idempotency_key") or "").strip() or None
    if key:
        row = find_by_key(conn, "tasks", key)
        if row:
            return row["id"]
    due = parse_ts(payload["due_at"]).isoformat().replace("+00:00", "Z") if payload.get("due_at") else None
    task_id = new_id("task")
    conn.execute(
        """INSERT INTO tasks
           (id,title,detail,category,priority,status,due_at,project_id,goal_id,source,
            idempotency_key,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            str(payload["title"]).strip()[:500],
            payload.get("detail"),
            payload.get("category"),
            to_int(payload.get("priority"), "priority", 3, 1, 5),
            payload.get("status") or "open",
            due,
            payload.get("project_id"),
            payload.get("goal_id"),
            payload.get("source") or "whatsapp",
            key,
            iso(),
            iso(),
        ),
    )
    return task_id


def task_add(conn, payload):
    key = (payload.get("idempotency_key") or "").strip() or None
    if key:
        row = find_by_key(conn, "tasks", key)
        if row:
            return {"id": row["id"], "deduplicated": True}
    with tx(conn):
        task_id = _insert_task(conn, payload)
    return {"id": task_id, "deduplicated": False}


def task_list(conn, payload):
    status = payload.get("status") or "active"
    limit = to_int(payload.get("limit"), "limit", 30, 1, 200)
    sql = "SELECT * FROM tasks"
    args: list = []
    if status == "active":
        sql += " WHERE status IN ('open','doing','blocked')"
    elif status != "all":
        sql += " WHERE status = ?"
        args.append(status)
    if payload.get("category"):
        sql += (" AND " if args else " WHERE ") + "category = ?"
        args.append(payload["category"])
    sql += " ORDER BY CASE priority WHEN 1 THEN 0 ELSE priority END, due_at IS NULL, due_at LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return {"tasks": [_task_view(r) for r in rows], "count": len(rows)}


def _task_view(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "priority": row["priority"],
        "due": display_ts(row["due_at"]),
        "due_at": row["due_at"],
        "category": row["category"],
        "goal_id": row["goal_id"],
    }


def task_update(conn, payload):
    require(payload, "id")
    allowed = {"title", "detail", "category", "priority", "status", "due_at", "goal_id",
               "project_id"}
    if payload.get("due_at"):
        payload = dict(payload, due_at=parse_ts(payload["due_at"]).isoformat().replace("+00:00", "Z"))
    sets, args = _patch_sets(payload, allowed)
    if not sets:
        raise ValueError("nothing to update")
    if payload.get("status") == "done":
        sets.append("completed_at = ?")
        args.append(iso())
        sets.append("status = 'done'")
    sets.append("updated_at = ?")
    args.append(iso())
    args.append(payload["id"])
    with tx(conn):
        cur = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", args)
    if cur.rowcount == 0:
        raise LookupError(f"task not found: {payload['id']}")
    return {"id": payload["id"], "updated": True}


def task_complete(conn, payload):
    require(payload, "id")
    with tx(conn):
        cur = conn.execute(
            """UPDATE tasks SET status='done', completed_at=?, updated_at=?
               WHERE id=? AND status <> 'done'""",
            (iso(), iso(), payload["id"]),
        )
        already = cur.rowcount == 0
    row = conn.execute("SELECT status FROM tasks WHERE id=?", (payload["id"],)).fetchone()
    if not row:
        raise LookupError(f"task not found: {payload['id']}")
    return {"id": payload["id"], "status": row["status"], "already_done": already}


def task_reschedule(conn, payload):
    require(payload, "id", "due_at")
    due = parse_ts(payload["due_at"]).isoformat().replace("+00:00", "Z")
    with tx(conn):
        cur = conn.execute(
            "UPDATE tasks SET due_at=?, updated_at=?, status=CASE WHEN status='done' THEN 'open' ELSE status END WHERE id=?",
            (due, iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"task not found: {payload['id']}")
    return {"id": payload["id"], "due": display_ts(due)}


def task_archive(conn, payload):
    require(payload, "id")
    with tx(conn):
        cur = conn.execute(
            "UPDATE tasks SET status='archived', archived_at=?, updated_at=? WHERE id=?",
            (iso(), iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"task not found: {payload['id']}")
    return {"id": payload["id"], "status": "archived"}


def _patch_sets(payload, allowed):
    sets, args = [], []
    for field in sorted(allowed):
        if field in payload:
            sets.append(f"{field} = ?")
            args.append(payload[field])
    return sets, args


# --------------------------------------------------------------------------- #
# goals + milestones
# --------------------------------------------------------------------------- #
def goal_add(conn, payload):
    require(payload, "title")
    goal_id = new_id("goal")
    with tx(conn):
        conn.execute(
            """INSERT INTO goals (id,title,why,deadline,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                goal_id,
                str(payload["title"])[:500],
                payload.get("why"),
                parse_ts(payload["deadline"]).isoformat().replace("+00:00", "Z") if payload.get("deadline") else None,
                payload.get("status") or "active",
                iso(),
                iso(),
            ),
        )
        for ms in payload.get("milestones") or []:
            _insert_milestone(conn, goal_id, ms)
    return {"id": goal_id}


def _insert_milestone(conn, goal_id, ms):
    if isinstance(ms, str):
        ms = {"title": ms}
    require(ms, "title")
    mid = new_id("ms")
    conn.execute(
        """INSERT INTO goal_milestones (id,goal_id,title,due_at,status,weight,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            mid,
            goal_id,
            str(ms["title"])[:300],
            parse_ts(ms["due_at"]).isoformat().replace("+00:00", "Z") if ms.get("due_at") else None,
            ms.get("status") or "open",
            float(ms.get("weight", 1.0)),
            iso(),
        ),
    )
    return mid


def goal_milestone_add(conn, payload):
    require(payload, "goal_id", "title")
    with tx(conn):
        mid = _insert_milestone(conn, payload["goal_id"], payload)
    return {"id": mid, "goal_id": payload["goal_id"]}


def goal_milestone_done(conn, payload):
    require(payload, "id")
    with tx(conn):
        cur = conn.execute(
            "UPDATE goal_milestones SET status='done', completed_at=? WHERE id=?",
            (iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"milestone not found: {payload['id']}")
    row = conn.execute("SELECT goal_id FROM goal_milestones WHERE id=?", (payload["id"],)).fetchone()
    return {"id": payload["id"], "goal_id": row["goal_id"], "progress": goal_progress(conn, row["goal_id"])}


def goal_progress(conn, goal_id: str) -> dict:
    rows = conn.execute(
        "SELECT status, weight FROM goal_milestones WHERE goal_id = ?", (goal_id,)
    ).fetchall()
    total = sum(r["weight"] for r in rows) or 0.0
    done = sum(r["weight"] for r in rows if r["status"] == "done")
    task_counts = Counter(
        r["status"]
        for r in conn.execute(
            "SELECT status FROM tasks WHERE goal_id = ? AND status <> 'archived'", (goal_id,)
        )
    )
    return {
        "goal_id": goal_id,
        "milestones_total": len(rows),
        "milestones_done": sum(1 for r in rows if r["status"] == "done"),
        "percent": round((done / total) * 100, 1) if total else 0.0,
        "tasks_open": task_counts.get("open", 0) + task_counts.get("doing", 0),
        "tasks_done": task_counts.get("done", 0),
    }


def goal_list(conn, payload):
    rows = conn.execute(
        "SELECT * FROM goals WHERE status IN ('active','paused') ORDER BY deadline IS NULL, deadline"
    ).fetchall()
    out = []
    for r in rows:
        p = goal_progress(conn, r["id"])
        out.append({
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "deadline": display_ts(r["deadline"]),
            "progress_percent": p["percent"],
            "milestones_done": p["milestones_done"],
            "milestones_total": p["milestones_total"],
        })
    return {"goals": out, "count": len(out)}


# --------------------------------------------------------------------------- #
# reminders
# --------------------------------------------------------------------------- #
def reminder_add(conn, payload):
    require(payload, "title", "due_at")
    key = (payload.get("dedupe_key") or "").strip() or None
    existing = None
    if key:
        existing = conn.execute(
            "SELECT * FROM reminders WHERE dedupe_key = ?", (key,)
        ).fetchone()
    due = parse_ts(payload["due_at"]).isoformat().replace("+00:00", "Z")
    if parse_ts(due) <= now_utc() - timedelta(seconds=5) and not payload.get("allow_past"):
        raise ValueError("due_at is in the past; pass allow_past=true to force")
    if existing:
        if existing["status"] in ("pending", "snoozed"):
            return {"id": existing["id"], "deduplicated": True}
        # A cancelled/sent reminder frees its key: reuse the row instead of
        # inserting a duplicate (dedupe_key is UNIQUE on purpose).
        with tx(conn):
            conn.execute(
                """UPDATE reminders SET title=?, body=?, due_at=?, recurrence=?, status='pending',
                   channel=?, snoozed_until=NULL, fired_at=NULL, attempts=0, updated_at=?
                   WHERE id=?""",
                (str(payload["title"])[:500], payload.get("body"), due,
                 payload.get("recurrence"), payload.get("channel") or "whatsapp", iso(),
                 existing["id"]),
            )
        return {"id": existing["id"], "due": display_ts(due), "reused": True,
                "deduplicated": False}

    rid = new_id("rem")
    with tx(conn):
        conn.execute(
            """INSERT INTO reminders
               (id,title,body,due_at,recurrence,status,channel,dedupe_key,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                str(payload["title"])[:500],
                payload.get("body"),
                due,
                payload.get("recurrence"),
                "pending",
                payload.get("channel") or "whatsapp",
                key,
                iso(),
                iso(),
            ),
        )
    return {"id": rid, "due": display_ts(due)}


def reminder_list(conn, payload):
    status = payload.get("status") or "pending"
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = ? ORDER BY due_at LIMIT ?",
        (status, to_int(payload.get("limit"), "limit", 50, 1, 200)),
    ).fetchall()
    return {
        "reminders": [
            {"id": r["id"], "title": r["title"], "status": r["status"],
             "due": display_ts(r["due_at"]), "recurrence": r["recurrence"]}
            for r in rows
        ],
        "count": len(rows),
    }


def reminder_cancel(conn, payload):
    require(payload, "id")
    with tx(conn):
        cur = conn.execute(
            "UPDATE reminders SET status='cancelled', updated_at=? WHERE id=? AND status IN ('pending','snoozed')",
            (iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        row = conn.execute("SELECT status FROM reminders WHERE id=?", (payload["id"],)).fetchone()
        if not row:
            raise LookupError(f"reminder not found: {payload['id']}")
        return {"id": payload["id"], "status": row["status"], "already": True}
    return {"id": payload["id"], "status": "cancelled"}


def reminder_snooze(conn, payload):
    require(payload, "id")
    minutes = to_int(payload.get("minutes"), "minutes", 15, 1, 60 * 24 * 30)
    target = iso(now_utc() + timedelta(minutes=minutes))
    with tx(conn):
        cur = conn.execute(
            "UPDATE reminders SET status='snoozed', snoozed_until=?, updated_at=? WHERE id=?",
            (target, iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"reminder not found: {payload['id']}")
    return {"id": payload["id"], "snoozed_until": display_ts(target)}


def reminder_due(conn, payload):
    """Pending reminders whose due_at has passed — used by the cron watchdog."""
    now = iso()
    rows = conn.execute(
        """SELECT * FROM reminders
           WHERE status IN ('pending','snoozed')
             AND COALESCE(snoozed_until, due_at) <= ?
           ORDER BY due_at LIMIT ?""",
        (now, to_int(payload.get("limit"), "limit", 20, 1, 100)),
    ).fetchall()
    return {
        "reminders": [
            {"id": r["id"], "title": r["title"], "due_at": r["due_at"],
             "due_local": display_ts(r["due_at"]), "recurrence": r["recurrence"],
             "channel": r["channel"]}
            for r in rows
        ],
        "count": len(rows),
    }


def reminder_mark_sent(conn, payload):
    require(payload, "id")
    with tx(conn):
        conn.execute(
            "UPDATE reminders SET status='sent', fired_at=?, attempts=attempts+1, updated_at=? WHERE id=?",
            (iso(), iso(), payload["id"]),
        )
    return {"id": payload["id"], "status": "sent"}


# --------------------------------------------------------------------------- #
# reviews
# --------------------------------------------------------------------------- #
def daily_review(conn, payload):
    day_start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=7)
    start = iso(day_start)
    done_today = conn.execute(
        "SELECT title, completed_at FROM tasks WHERE completed_at >= ? ORDER BY completed_at DESC",
        (start,),
    ).fetchall()
    open_tasks = conn.execute(
        """SELECT title, priority, due_at FROM tasks
           WHERE status IN ('open','doing','blocked')
           ORDER BY due_at IS NULL, due_at LIMIT 50"""
    ).fetchall()
    due_soon = [t for t in open_tasks if t["due_at"] and t["due_at"] <= iso(now_utc() + timedelta(days=1))]
    reminders = conn.execute(
        "SELECT title, due_at FROM reminders WHERE status='pending' ORDER BY due_at LIMIT 20"
    ).fetchall()
    inbox_new = conn.execute(
        "SELECT COUNT(*) AS c FROM inbox_items WHERE status='new'"
    ).fetchone()["c"]
    return {
        "date_local": _jakarta_date(),
        "done_today": [{"title": r["title"], "at": display_ts(r["completed_at"])} for r in done_today],
        "open_count": len(open_tasks),
        "due_within_24h": [
            {"title": r["title"], "due": display_ts(r["due_at"]), "priority": r["priority"]}
            for r in due_soon
        ],
        "reminders": [{"title": r["title"], "due": display_ts(r["due_at"])} for r in reminders],
        "inbox_new": inbox_new,
    }


def _jakarta_date() -> str:
    from ..util import JAKARTA
    return now_utc().astimezone(JAKARTA).strftime("%Y-%m-%d")


def weekly_review(conn, payload):
    week_start = iso(now_utc() - timedelta(days=7))
    done = conn.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE completed_at >= ?", (week_start,)
    ).fetchone()["c"]
    created = conn.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE created_at >= ?", (week_start,)
    ).fetchone()["c"]
    goals = goal_list(conn, {})["goals"]
    completed_titles = [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM tasks WHERE completed_at >= ? ORDER BY completed_at DESC LIMIT 20",
            (week_start,),
        )
    ]
    study = conn.execute(
        "SELECT COUNT(*) AS c FROM study_attempts WHERE created_at >= ?", (week_start,)
    ).fetchone()["c"]
    return {
        "tasks_completed": done,
        "tasks_created": created,
        "study_attempts": study,
        "goals": goals,
        "completed_titles": completed_titles,
    }


def _goal_status(conn, payload):
    require(payload, "id")
    row = conn.execute("SELECT * FROM goals WHERE id=?", (payload["id"],)).fetchone()
    if not row:
        raise LookupError(f"goal not found: {payload['id']}")
    return {"goal": {"id": row["id"], "title": row["title"], "status": row["status"]},
            "progress": goal_progress(conn, payload["id"])}


ACTIONS = {
    "inbox.add": inbox_add,
    "inbox.list": inbox_list,
    "inbox.update": inbox_update,
    "inbox.promote": inbox_promote,
    "notes.add": notes_add,
    "notes.search": notes_search,
    "task.add": task_add,
    "task.list": task_list,
    "task.update": task_update,
    "task.complete": task_complete,
    "task.reschedule": task_reschedule,
    "task.archive": task_archive,
    "goal.add": goal_add,
    "goal.list": goal_list,
    "goal.status": _goal_status,
    "milestone.add": goal_milestone_add,
    "milestone.done": goal_milestone_done,
    "reminder.add": reminder_add,
    "reminder.list": reminder_list,
    "reminder.cancel": reminder_cancel,
    "reminder.snooze": reminder_snooze,
    "reminder.due": reminder_due,
    "reminder.mark_sent": reminder_mark_sent,
    "review.daily": daily_review,
    "review.weekly": weekly_review,
}
