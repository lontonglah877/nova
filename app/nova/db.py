"""SQLite access layer: versioned migrations, transactions, idempotency.

The NOVA database is separate from Hermes (~/.hermes/state.db). Never open that one.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .util import now_utc, iso

DEFAULT_DB = "data/nova.sqlite"


def db_path() -> Path:
    """NOVA_HOME/data/nova.sqlite unless NOVA_DB points elsewhere."""
    explicit = os.environ.get("NOVA_DB")
    if explicit:
        return Path(explicit).expanduser()
    home = Path(os.environ.get("NOVA_HOME") or (Path.home() / "nova"))
    return home / DEFAULT_DB


# --------------------------------------------------------------------------- #
# Migrations (append only — never edit a version that has shipped)
# --------------------------------------------------------------------------- #
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "core schema",
        """
        CREATE TABLE inbox_items (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            body            TEXT,
            kind            TEXT NOT NULL DEFAULT 'note'
                            CHECK (kind IN ('note','task','idea','link','document','question')),
            status          TEXT NOT NULL DEFAULT 'new'
                            CHECK (status IN ('new','classified','promoted','done','archived')),
            category        TEXT,
            project_id      TEXT,
            source          TEXT NOT NULL DEFAULT 'whatsapp',
            idempotency_key TEXT UNIQUE,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            archived_at     TEXT
        );

        CREATE TABLE notes (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            body        TEXT,
            tags        TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE goals (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            why         TEXT,
            deadline    TEXT,
            status      TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','paused','done','dropped')),
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE tasks (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            detail          TEXT,
            category        TEXT,
            priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
            status          TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open','doing','done','blocked','dropped','archived')),
            due_at          TEXT,
            project_id      TEXT,
            goal_id         TEXT REFERENCES goals(id) ON DELETE SET NULL,
            source          TEXT NOT NULL DEFAULT 'whatsapp',
            idempotency_key TEXT UNIQUE,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            completed_at    TEXT,
            archived_at     TEXT
        );

        CREATE TABLE goal_milestones (
            id          TEXT PRIMARY KEY,
            goal_id     TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            due_at      TEXT,
            status      TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','done','dropped')),
            weight      REAL NOT NULL DEFAULT 1.0,
            created_at  TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE reminders (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            body            TEXT,
            due_at          TEXT NOT NULL,
            recurrence      TEXT,
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','sent','cancelled','snoozed','failed')),
            channel         TEXT NOT NULL DEFAULT 'whatsapp',
            dedupe_key      TEXT UNIQUE,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            snoozed_until   TEXT,
            fired_at        TEXT,
            attempts        INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE projects (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            objective      TEXT,
            status         TEXT NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active','paused','done','dropped')),
            workspace_path TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE TABLE project_tasks (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id     TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','doing','done','dropped')),
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE documents (
            id            TEXT PRIMARY KEY,
            path          TEXT NOT NULL,
            original_name TEXT NOT NULL,
            mime          TEXT,
            size_bytes    INTEGER NOT NULL,
            sha256        TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'stored'
                          CHECK (status IN ('stored','extracted','unsupported','oversize','error')),
            extracted_text TEXT,
            summary       TEXT,
            error         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE document_tags (
            id          TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            tag         TEXT NOT NULL,
            UNIQUE (document_id, tag)
        );

        CREATE TABLE study_topics (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            system      TEXT,
            notes       TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE flashcards (
            id            TEXT PRIMARY KEY,
            topic_id      TEXT REFERENCES study_topics(id) ON DELETE SET NULL,
            front         TEXT NOT NULL,
            back          TEXT NOT NULL,
            source        TEXT,
            ease          REAL NOT NULL DEFAULT 2.5,
            interval_days INTEGER NOT NULL DEFAULT 0,
            reps          INTEGER NOT NULL DEFAULT 0,
            lapses        INTEGER NOT NULL DEFAULT 0,
            due_at        TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE study_attempts (
            id          TEXT PRIMARY KEY,
            topic_id    TEXT REFERENCES study_topics(id) ON DELETE SET NULL,
            flashcard_id TEXT REFERENCES flashcards(id) ON DELETE SET NULL,
            mode        TEXT NOT NULL DEFAULT 'quiz',
            question    TEXT,
            answer      TEXT,
            score       REAL,
            correct     INTEGER CHECK (correct IN (0,1) OR correct IS NULL),
            created_at  TEXT NOT NULL
        );

        CREATE TABLE study_reviews (
            id          TEXT PRIMARY KEY,
            topic_id    TEXT REFERENCES study_topics(id) ON DELETE CASCADE,
            flashcard_id TEXT REFERENCES flashcards(id) ON DELETE CASCADE,
            scheduled_for TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','done','missed','cancelled')),
            created_at  TEXT NOT NULL,
            done_at     TEXT
        );

        CREATE TABLE market_watchlist (
            id          TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            venue       TEXT NOT NULL DEFAULT 'unknown',
            note        TEXT,
            created_at  TEXT NOT NULL,
            UNIQUE (symbol, venue)
        );

        CREATE TABLE market_snapshots (
            id          TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            venue       TEXT NOT NULL,
            price       REAL NOT NULL,
            source      TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            UNIQUE (symbol, venue, observed_at, source)
        );

        CREATE TABLE trading_signals (
            id          TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            venue       TEXT NOT NULL,
            side        TEXT NOT NULL CHECK (side IN ('long','short','flat','watch')),
            confidence  REAL,
            rationale   TEXT,
            source      TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            payload_json TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE trading_journal (
            id          TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            venue       TEXT NOT NULL DEFAULT 'unknown',
            side        TEXT NOT NULL CHECK (side IN ('long','short')),
            entry_price REAL NOT NULL,
            exit_price  REAL,
            stop_loss   REAL,
            take_profit REAL,
            size        REAL,
            fees        REAL NOT NULL DEFAULT 0,
            opened_at   TEXT NOT NULL,
            closed_at   TEXT,
            notes       TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE notifications (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            body        TEXT NOT NULL,
            channel     TEXT NOT NULL DEFAULT 'whatsapp',
            status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','sent','failed','skipped')),
            scheduled_for TEXT,
            sent_at     TEXT,
            attempts    INTEGER NOT NULL DEFAULT 0,
            dedupe_key  TEXT UNIQUE,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE decisions (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            context     TEXT,
            decision    TEXT NOT NULL,
            alternatives TEXT,
            project_id  TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE system_events (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            severity    TEXT NOT NULL DEFAULT 'info'
                        CHECK (severity IN ('info','warn','error')),
            message     TEXT NOT NULL,
            meta_json   TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE backup_history (
            id          TEXT PRIMARY KEY,
            path        TEXT NOT NULL,
            size_bytes  INTEGER NOT NULL,
            sha256      TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'auto',
            created_at  TEXT NOT NULL,
            verified_at TEXT
        );

        CREATE INDEX idx_tasks_status_due   ON tasks(status, due_at);
        CREATE INDEX idx_tasks_goal         ON tasks(goal_id);
        CREATE INDEX idx_tasks_project      ON tasks(project_id);
        CREATE INDEX idx_inbox_status       ON inbox_items(status, created_at);
        CREATE INDEX idx_reminders_status   ON reminders(status, due_at);
        CREATE INDEX idx_flashcards_due     ON flashcards(due_at);
        CREATE INDEX idx_study_reviews_due  ON study_reviews(status, scheduled_for);
        CREATE INDEX idx_snapshots_symbol   ON market_snapshots(symbol, observed_at);
        CREATE INDEX idx_signals_symbol     ON trading_signals(symbol, observed_at);
        CREATE INDEX idx_notifications_stat ON notifications(status, scheduled_for);
        CREATE INDEX idx_events_kind        ON system_events(kind, created_at);
        CREATE INDEX idx_docs_status        ON documents(status, created_at);
        """,
    ),
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations. Returns the versions applied in this call."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY,
               name       TEXT NOT NULL,
               applied_at TEXT NOT NULL
           )"""
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[int] = []
    for version, name, sql in MIGRATIONS:
        if version in done:
            continue
        # NOTE: executescript() implicitly COMMITs, which would break an explicit
        # transaction. Run each statement individually inside BEGIN IMMEDIATE so a
        # half-applied migration can never be recorded as done.
        statements = [s.strip() for s in _split_sql(sql) if s.strip()]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                (version, name, iso()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _split_sql(sql: str) -> list[str]:
    """Split DDL on statement terminators. Our migrations contain no ';' inside literals."""
    out, buf = [], []
    for line in sql.splitlines():
        stripped = line.split("--")[0] if line.strip().startswith("--") else line
        buf.append(stripped)
        if stripped.rstrip().endswith(";"):
            out.append("\n".join(buf))
            buf = []
    if "".join(buf).strip():
        out.append("\n".join(buf))
    return out


@contextmanager
def tx(conn: sqlite3.Connection, immediate: bool = True):
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def open_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


def find_by_key(conn: sqlite3.Connection, table: str, key: str) -> sqlite3.Row | None:
    if not key:
        return None
    row = conn.execute(
        f"SELECT * FROM {table} WHERE idempotency_key = ?", (key,)
    ).fetchone()
    return row
