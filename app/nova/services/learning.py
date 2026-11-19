"""Medical learning: topics, flashcards (SM-2 style scheduling), attempts."""

from __future__ import annotations

from datetime import timedelta

from ..db import find_by_key, tx
from ..util import display_ts, iso, new_id, now_utc, parse_ts, require, to_float, to_int

QUALITY_GRADES = {"again": 0, "hard": 3, "good": 4, "easy": 5}


def topic_add(conn, payload):
    require(payload, "name")
    name = str(payload["name"]).strip()[:300]
    row = conn.execute("SELECT id FROM study_topics WHERE name = ?", (name,)).fetchone()
    if row:
        return {"id": row["id"], "deduplicated": True}
    tid = new_id("topic")
    with tx(conn):
        conn.execute(
            """INSERT INTO study_topics (id,name,system,notes,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (tid, name, payload.get("system"), payload.get("notes"), iso(), iso()),
        )
    return {"id": tid, "deduplicated": False}


def topic_list(conn, payload):
    rows = conn.execute(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM flashcards f WHERE f.topic_id = t.id) AS cards,
                  (SELECT COUNT(*) FROM flashcards f WHERE f.topic_id = t.id AND f.due_at <= ?) AS due
           FROM study_topics t ORDER BY t.name""",
        (iso(),),
    ).fetchall()
    return {
        "topics": [
            {"id": r["id"], "name": r["name"], "system": r["system"],
             "cards": r["cards"], "due": r["due"]}
            for r in rows
        ],
        "count": len(rows),
    }


def card_add(conn, payload):
    require(payload, "front", "back")
    topic_id = payload.get("topic_id")
    if not topic_id and payload.get("topic"):
        topic_id = topic_add(conn, {"name": payload["topic"]})["id"]
    key = (payload.get("idempotency_key") or "").strip() or None
    if key:
        row = find_by_key(conn, "flashcards", key)
        if row:
            return {"id": row["id"], "deduplicated": True}
    cid = new_id("card")
    with tx(conn):
        conn.execute(
            """INSERT INTO flashcards
               (id,topic_id,front,back,source,ease,interval_days,reps,lapses,due_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, topic_id, str(payload["front"])[:2000], str(payload["back"])[:4000],
                payload.get("source"), 2.5, 0, 0, 0, iso(), iso(), iso(),
            ),
        )
    return {"id": cid, "topic_id": topic_id, "deduplicated": False}


def card_due(conn, payload):
    limit = to_int(payload.get("limit"), "limit", 20, 1, 100)
    topic = payload.get("topic_id")
    args = [iso()]
    sql = "SELECT * FROM flashcards WHERE due_at <= ?"
    if topic:
        sql += " AND topic_id = ?"
        args.append(topic)
    sql += " ORDER BY due_at LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return {
        "cards": [
            {"id": r["id"], "front": r["front"], "back": r["back"], "reps": r["reps"],
             "due": display_ts(r["due_at"]), "topic_id": r["topic_id"]}
            for r in rows
        ],
        "count": len(rows),
    }


def card_review(conn, payload):
    """SM-2 scheduling. grade: again|hard|good|easy."""
    require(payload, "id", "grade")
    grade = str(payload["grade"]).strip().lower()
    if grade not in QUALITY_GRADES:
        raise ValueError("grade must be one of: " + ", ".join(QUALITY_GRADES))
    row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (payload["id"],)).fetchone()
    if not row:
        raise LookupError(f"card not found: {payload['id']}")
    q = QUALITY_GRADES[grade]
    ease, interval, reps, lapses = row["ease"], row["interval_days"], row["reps"], row["lapses"]
    if q < 3:
        reps = 0
        lapses += 1
        interval = 0
        next_due = now_utc() + timedelta(minutes=10)
        ease = max(1.3, ease - 0.2)
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = int(round(interval * ease))
        ease = max(1.3, ease + (0.15 if q == 5 else 0.0) - (0.15 if q == 3 else 0.0))
        next_due = now_utc() + timedelta(days=max(1, interval))
    with tx(conn):
        conn.execute(
            """UPDATE flashcards SET ease=?, interval_days=?, reps=?, lapses=?, due_at=?,
               updated_at=? WHERE id=?""",
            (ease, interval, reps, lapses, iso(next_due), iso(), row["id"]),
        )
        conn.execute(
            """INSERT INTO study_reviews
               (id,topic_id,flashcard_id,scheduled_for,status,created_at)
               VALUES (?,?,?,?,'pending',?)""",
            (new_id("rev"), row["topic_id"], row["id"], iso(next_due), iso()),
        )
        conn.execute(
            """INSERT INTO study_attempts
               (id,topic_id,flashcard_id,mode,question,answer,score,correct,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (new_id("att"), row["topic_id"], row["id"], "flashcard", row["front"],
             grade, float(q), 1 if q >= 3 else 0, iso()),
        )
    return {
        "id": row["id"],
        "next_due": display_ts(next_due),
        "interval_days": interval,
        "ease": round(ease, 2),
        "lapses": lapses,
    }


def attempt_add(conn, payload):
    """Quiz / case attempt that is not tied to a single flashcard."""
    topic_id = payload.get("topic_id")
    if not topic_id and payload.get("topic"):
        topic_id = topic_add(conn, {"name": payload["topic"]})["id"]
    correct = payload.get("correct")
    aid = new_id("att")
    with tx(conn):
        conn.execute(
            """INSERT INTO study_attempts
               (id,topic_id,flashcard_id,mode,question,answer,score,correct,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                aid, topic_id, None, payload.get("mode") or "quiz",
                payload.get("question"), payload.get("answer"),
                to_float(payload.get("score"), "score"),
                None if correct is None else (1 if bool(correct) else 0),
                iso(),
            ),
        )
    return {"id": aid, "topic_id": topic_id}


def progress(conn, payload):
    week_start = iso(now_utc() - timedelta(days=7))
    total_cards = conn.execute("SELECT COUNT(*) AS c FROM flashcards").fetchone()["c"]
    due_now = conn.execute(
        "SELECT COUNT(*) AS c FROM flashcards WHERE due_at <= ?", (iso(),)
    ).fetchone()["c"]
    attempts_7d = conn.execute(
        "SELECT COUNT(*) AS c FROM study_attempts WHERE created_at >= ?", (week_start,)
    ).fetchone()["c"]
    correct_7d = conn.execute(
        "SELECT COUNT(*) AS c FROM study_attempts WHERE created_at >= ? AND correct = 1",
        (week_start,),
    ).fetchone()["c"]
    weak = conn.execute(
        """SELECT t.name AS topic, COUNT(a.id) AS misses
           FROM study_attempts a LEFT JOIN study_topics t ON t.id = a.topic_id
           WHERE a.correct = 0 AND a.created_at >= ?
           GROUP BY t.name ORDER BY misses DESC LIMIT 5""",
        (week_start,),
    ).fetchall()
    return {
        "cards_total": total_cards,
        "cards_due": due_now,
        "attempts_7d": attempts_7d,
        "accuracy_7d": round(correct_7d / attempts_7d, 3) if attempts_7d else None,
        "weak_topics": [{"topic": r["topic"], "misses": r["misses"]} for r in weak],
        "topics": topic_list(conn, {})["topics"],
    }


def review_due(conn, payload):
    rows = conn.execute(
        "SELECT * FROM study_reviews WHERE status='pending' AND scheduled_for <= ? ORDER BY scheduled_for LIMIT ?",
        (iso(), to_int(payload.get("limit"), "limit", 20, 1, 100)),
    ).fetchall()
    return {
        "reviews": [
            {"id": r["id"], "flashcard_id": r["flashcard_id"], "topic_id": r["topic_id"],
             "scheduled_for": display_ts(r["scheduled_for"])}
            for r in rows
        ],
        "count": len(rows),
    }


ACTIONS = {
    "topic.add": topic_add,
    "topic.list": topic_list,
    "card.add": card_add,
    "card.due": card_due,
    "card.review": card_review,
    "attempt.add": attempt_add,
    "progress": progress,
    "review.due": review_due,
}
