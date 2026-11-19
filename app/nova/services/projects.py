"""Projects: bounded workspace, milestones, decision log."""

from __future__ import annotations

import os
from pathlib import Path

from ..db import tx
from ..util import display_ts, iso, new_id, require, to_int


def _workspace_root() -> Path:
    return Path(os.environ.get("NOVA_WORKSPACE") or (Path(os.environ.get("NOVA_HOME") or (Path.home() / "nova")) / "workspace"))


def _safe_ws(path_value: str) -> Path:
    """A project workspace must live under NOVA_WORKSPACE. Never escape it."""
    root = _workspace_root().resolve()
    candidate = (root / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError(f"workspace escapes NOVA_WORKSPACE: {path_value}")
    return candidate


def project_add(conn, payload):
    require(payload, "name")
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-"
                   for ch in str(payload["name"]).strip().lower())[:60].strip("-") or "project"
    ws = _safe_ws(payload.get("workspace") or slug)
    ws.mkdir(parents=True, exist_ok=True)
    pid = new_id("prj")
    with tx(conn):
        conn.execute(
            """INSERT INTO projects (id,name,objective,status,workspace_path,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, str(payload["name"])[:300], payload.get("objective"),
             payload.get("status") or "active", str(ws), iso(), iso()),
        )
    return {"id": pid, "workspace": str(ws)}


def project_list(conn, payload):
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        counts = conn.execute(
            "SELECT status, COUNT(*) AS c FROM project_tasks WHERE project_id=? GROUP BY status",
            (r["id"],),
        ).fetchall()
        by = {c["status"]: c["c"] for c in counts}
        out.append({
            "id": r["id"], "name": r["name"], "status": r["status"],
            "workspace": r["workspace_path"],
            "tasks_open": by.get("open", 0) + by.get("doing", 0),
            "tasks_done": by.get("done", 0),
        })
    return {"projects": out, "count": len(out)}


def ptask_add(conn, payload):
    require(payload, "project_id", "title")
    if not conn.execute("SELECT 1 FROM projects WHERE id=?", (payload["project_id"],)).fetchone():
        raise LookupError(f"project not found: {payload['project_id']}")
    tid = new_id("pt")
    with tx(conn):
        conn.execute(
            """INSERT INTO project_tasks (id,project_id,task_id,title,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (tid, payload["project_id"], payload.get("task_id"),
             str(payload["title"])[:500], payload.get("status") or "open", iso(), iso()),
        )
    return {"id": tid}


def ptask_update(conn, payload):
    require(payload, "id")
    if payload.get("status") not in (None, "open", "doing", "done", "dropped"):
        raise ValueError("status must be open, doing, done or dropped")
    with tx(conn):
        cur = conn.execute(
            "UPDATE project_tasks SET status=COALESCE(?,status), title=COALESCE(?,title), updated_at=? WHERE id=?",
            (payload.get("status"), payload.get("title"), iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"project task not found: {payload['id']}")
    return {"id": payload["id"], "updated": True}


def decision_log(conn, payload):
    if payload.get("action_", None) or payload.get("log"):
        require(payload, "title", "decision")
        did = new_id("dec")
        with tx(conn):
            conn.execute(
                """INSERT INTO decisions (id,title,context,decision,alternatives,project_id,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (did, payload["title"], payload.get("context"), payload["decision"],
                 payload.get("alternatives"), payload.get("project_id"), iso()),
            )
        return {"id": did}
    rows = conn.execute(
        "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
        (to_int(payload.get("limit"), "limit", 20, 1, 100),),
    ).fetchall()
    return {
        "decisions": [
            {"id": r["id"], "title": r["title"], "decision": r["decision"],
             "created": display_ts(r["created_at"])}
            for r in rows
        ],
        "count": len(rows),
    }


def file_index(conn, payload):
    """Read-only listing of a project workspace (no writes, no deletion)."""
    require(payload, "project_id")
    row = conn.execute("SELECT workspace_path FROM projects WHERE id=?", (payload["project_id"],)).fetchone()
    if not row:
        raise LookupError(f"project not found: {payload['project_id']}")
    base = Path(row["workspace_path"])
    if not base.exists():
        return {"files": [], "count": 0, "note": "workspace missing on disk"}
    files, total = [], 0
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            total += size
            files.append({"path": str(fp.relative_to(base)).replace("\\", "/"), "size": size})
            if len(files) >= 500:
                break
    return {"files": files, "count": len(files), "bytes": total}


ACTIONS = {
    "add": project_add,
    "list": project_list,
    "task.add": ptask_add,
    "task.update": ptask_update,
    "decision": decision_log,
    "files": file_index,
}
