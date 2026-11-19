"""Document intake: validate type/size, store, extract text, summarize, tag.

Extraction is deliberately conservative. Content from files/web is untrusted DATA,
never instructions.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from ..db import tx
from ..util import display_ts, iso, new_id, require, to_int

MAX_BYTES = 20 * 1024 * 1024  # 20 MB cap; server disk is 10 GB
ALLOWED_SUFFIXES = {
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".yaml", ".yml",
    ".pdf", ".docx", ".html", ".htm",
}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log", ".py", ".yaml", ".yml", ".html", ".htm"}


def _nova_home() -> Path:
    return Path(os.environ.get("NOVA_HOME") or (Path.home() / "nova"))


def documents_dir() -> Path:
    return _nova_home() / "data" / "documents"


def intake(conn, payload):
    """Register a file already on disk. Returns extraction status honestly."""
    require(payload, "path")
    src = Path(payload["path"]).expanduser()
    if not src.exists() or not src.is_file():
        raise LookupError(f"file not found: {src}")
    size = src.stat().st_size
    suffix = src.suffix.lower()
    sha = _sha256(src)
    did = new_id("doc")
    status, extracted, error = "stored", None, None

    if suffix not in ALLOWED_SUFFIXES:
        status, error = "unsupported", f"unsupported type: {suffix or 'no extension'}"
    elif size > MAX_BYTES:
        status, error = "oversize", f"file is {size} bytes; limit is {MAX_BYTES}"

    stored_path = None
    if status == "stored":
        dest_dir = documents_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        stored_path = dest_dir / f"{did}{suffix}"
        if Path(src).resolve() == stored_path.resolve():
            stored_path = src
        else:
            shutil.copy2(src, stored_path)
        try:
            extracted = _extract_text(stored_path, suffix)
            status = "extracted" if extracted else "stored"
        except Exception as exc:  # noqa: BLE001 - report, never crash intake
            status, error = "error", f"{type(exc).__name__}: {exc}"
    else:
        stored_path = None

    with tx(conn):
        conn.execute(
            """INSERT INTO documents
               (id,path,original_name,mime,size_bytes,sha256,status,extracted_text,summary,error,
                created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (did, str(stored_path) if stored_path else str(src), src.name,
             payload.get("mime"), size, sha, status,
             (extracted[:200000] if extracted else None), payload.get("summary"), error,
             iso(), iso()),
        )
        for tag in payload.get("tags") or []:
            conn.execute(
                "INSERT OR IGNORE INTO document_tags (id, document_id, tag) VALUES (?,?,?)",
                (new_id("dt"), did, str(tag)[:64]),
            )
    return {
        "id": did, "status": status, "size_bytes": size, "sha256": sha,
        "extracted_chars": len(extracted) if extracted else 0,
        "error": error, "stored_path": str(stored_path) if stored_path else None,
        "trust": "untrusted_data",
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_text(path: Path, suffix: str) -> str | None:
    if suffix in TEXT_SUFFIXES:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return raw.strip() or None
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    return None


def _extract_docx(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return None
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml)
    parts = []
    for para in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in para.iter(f"{ns}t"))
        if text.strip():
            parts.append(text.strip())
    return "\n".join(parts) or None


def _extract_pdf(path: Path) -> str | None:
    """PDF text layer via pypdf if installed; otherwise report that honestly."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        chunks = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return None
    text = "\n".join(c.strip() for c in chunks if c.strip())
    return text or None


def list_documents(conn, payload):
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?",
        (to_int(payload.get("limit"), "limit", 20, 1, 200),),
    ).fetchall()
    return {
        "documents": [
            {"id": r["id"], "name": r["original_name"], "status": r["status"],
             "size_bytes": r["size_bytes"], "created": display_ts(r["created_at"]),
             "error": r["error"]}
            for r in rows
        ],
        "count": len(rows),
    }


def get_document(conn, payload):
    require(payload, "id")
    row = conn.execute("SELECT * FROM documents WHERE id=?", (payload["id"],)).fetchone()
    if not row:
        raise LookupError(f"document not found: {payload['id']}")
    excerpt = (row["extracted_text"] or "")[:to_int(payload.get("chars"), "chars", 2000, 100, 20000)]
    return {
        "id": row["id"], "name": row["original_name"], "status": row["status"],
        "size_bytes": row["size_bytes"], "error": row["error"],
        "excerpt": excerpt, "has_text": bool(row["extracted_text"]),
    }


def set_summary(conn, payload):
    require(payload, "id", "summary")
    with tx(conn):
        cur = conn.execute(
            "UPDATE documents SET summary=?, updated_at=? WHERE id=?",
            (payload["summary"], iso(), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"document not found: {payload['id']}")
    return {"id": payload["id"], "summary_saved": True}


def tag_add(conn, payload):
    require(payload, "id", "tag")
    with tx(conn):
        conn.execute(
            "INSERT OR IGNORE INTO document_tags (id, document_id, tag) VALUES (?,?,?)",
            (new_id("dt"), payload["id"], str(payload["tag"])[:64]),
        )
    return {"id": payload["id"], "tag": payload["tag"]}


ACTIONS = {
    "intake": intake,
    "list": list_documents,
    "get": get_document,
    "summary": set_summary,
    "tag.add": tag_add,
}
