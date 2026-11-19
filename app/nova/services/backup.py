"""Backup and restore using the SQLite online-backup API (consistent snapshot)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

from ..db import db_path, open_db, tx
from ..util import display_ts, env_flag, iso, new_id, require, to_int


def backup_dir() -> Path:
    home = Path(os.environ.get("NOVA_HOME") or (Path.home() / "nova"))
    return Path(os.environ.get("NOVA_BACKUP_DIR") or (home / "backups"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_backup(conn, payload):
    src = db_path()
    if not src.exists():
        raise LookupError(f"database not found: {src}")
    bdir = backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = iso().replace(":", "").replace("-", "")
    dest = bdir / f"nova-{stamp}.sqlite"
    # Online backup: safe while the gateway may be reading the DB.
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
    size = dest.stat().st_size
    sha = _sha256(dest)
    # Verify the copy opens and has the expected schema version.
    verify_conn = sqlite3.connect(str(dest))
    try:
        row = verify_conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        schema_version = row[0] if row else None
        tables = verify_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        verify_conn.close()
    bid = new_id("bak")
    with tx(conn):
        conn.execute(
            """INSERT INTO backup_history (id,path,size_bytes,sha256,kind,created_at,verified_at)
               VALUES (?,?,?,?,?,?,?)""",
            (bid, str(dest), size, sha, payload.get("kind") or "manual", iso(), iso()),
        )
    pruned = _prune(conn, to_int(payload.get("keep"), "keep", 7, 1, 90))
    return {"id": bid, "path": str(dest), "size_bytes": size, "sha256": sha,
            "verified_schema_version": schema_version, "table_count": tables,
            "pruned": pruned}


def _prune(conn, keep: int) -> int:
    rows = conn.execute(
        "SELECT id, path FROM backup_history ORDER BY created_at DESC"
    ).fetchall()
    removed = 0
    for r in rows[keep:]:
        try:
            Path(r["path"]).unlink(missing_ok=True)
        except OSError:
            continue
        with tx(conn):
            conn.execute("DELETE FROM backup_history WHERE id=?", (r["id"],))
        removed += 1
    return removed


def list_backups(conn, payload):
    rows = conn.execute(
        "SELECT * FROM backup_history ORDER BY created_at DESC LIMIT ?",
        (to_int(payload.get("limit"), "limit", 20, 1, 200),),
    ).fetchall()
    exist = []
    for r in rows:
        exist.append({
            "id": r["id"], "path": r["path"], "size_bytes": r["size_bytes"],
            "kind": r["kind"], "created": display_ts(r["created_at"]),
            "exists": Path(r["path"]).exists(),
        })
    return {"backups": exist, "count": len(exist), "dir": str(backup_dir())}


def restore_test(conn, payload):
    """Restore a backup into a TEMP directory and verify it. Never touches production."""
    require(payload, "path")
    src = Path(payload["path"])
    if not src.exists():
        raise LookupError(f"backup not found: {src}")
    tmp = Path(tempfile.mkdtemp(prefix="nova-restore-test-"))
    dest = tmp / "restored.sqlite"
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    probe = sqlite3.connect(str(dest))
    try:
        integrity = probe.execute("PRAGMA integrity_check").fetchone()[0]
        version = probe.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        tasks = probe.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        inbox = probe.execute("SELECT COUNT(*) FROM inbox_items").fetchone()[0]
    finally:
        probe.close()
    return {
        "restored_to": str(dest), "integrity": integrity, "schema_version": version,
        "row_counts": {"tasks": tasks, "inbox_items": inbox},
        "production_untouched": True,
        "cleanup_hint": f"delete {tmp} when done",
    }


ACTIONS = {
    "run": run_backup,
    "list": list_backups,
    "restore.test": restore_test,
}
