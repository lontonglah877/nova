"""Trading: read-only market data intake, signals, journal, performance.

Order execution is intentionally absent. Every price/signal row carries `source`
and `observed_at` so nothing is ever presented without provenance.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from ..db import tx
from ..util import display_ts, iso, new_id, now_utc, parse_ts, require, to_float, to_int

REQUIRED_SNAPSHOT_FIELDS = ("symbol", "price", "source", "observed_at")


# --------------------------------------------------------------------------- #
# watchlist
# --------------------------------------------------------------------------- #
def watch_add(conn, payload):
    require(payload, "symbol")
    symbol = str(payload["symbol"]).strip().upper()[:64]
    venue = (payload.get("venue") or "unknown").strip().lower()[:64]
    existing = conn.execute(
        "SELECT id FROM market_watchlist WHERE symbol=? AND venue=?", (symbol, venue)
    ).fetchone()
    if existing:
        return {"id": existing["id"], "deduplicated": True}
    wid = new_id("watch")
    with tx(conn):
        conn.execute(
            """INSERT INTO market_watchlist (id,symbol,venue,note,created_at)
               VALUES (?,?,?,?,?)""",
            (wid, symbol, venue, payload.get("note"), iso()),
        )
    return {"id": wid, "symbol": symbol, "venue": venue, "deduplicated": False}


def watch_list(conn, payload):
    rows = conn.execute("SELECT * FROM market_watchlist ORDER BY symbol").fetchall()
    out = []
    for r in rows:
        last = conn.execute(
            """SELECT price, source, observed_at FROM market_snapshots
               WHERE symbol=? AND venue=? ORDER BY observed_at DESC LIMIT 1""",
            (r["symbol"], r["venue"]),
        ).fetchone()
        out.append({
            "id": r["id"], "symbol": r["symbol"], "venue": r["venue"],
            "last_price": last["price"] if last else None,
            "last_source": last["source"] if last else None,
            "last_observed": display_ts(last["observed_at"]) if last else None,
            "stale": _is_stale(last["observed_at"]) if last else True,
        })
    return {"watchlist": out, "count": len(out), "data_status": _data_status(out)}


def _is_stale(observed_at: str, max_age_minutes: int = 60 * 24) -> bool:
    try:
        return parse_ts(observed_at) < now_utc() - timedelta(minutes=max_age_minutes)
    except ValueError:
        return True


def _data_status(items) -> str:
    if not items:
        return "not_configured"
    if any(i["last_price"] is not None for i in items):
        return "live_snapshot"
    return "not_configured"


# --------------------------------------------------------------------------- #
# snapshots / import
# --------------------------------------------------------------------------- #
def snapshot_add(conn, payload):
    for f in REQUIRED_SNAPSHOT_FIELDS:
        if payload.get(f) in (None, ""):
            raise ValueError(f"missing required field(s): {f}")
    symbol = str(payload["symbol"]).strip().upper()[:64]
    venue = (payload.get("venue") or "unknown").strip().lower()[:64]
    price = to_float(payload["price"], "price")
    if price is None or price <= 0:
        raise ValueError("price must be a positive number")
    source = str(payload["source"]).strip()[:200]
    observed = parse_ts(payload["observed_at"], "observed_at")
    observed_iso = iso(observed)
    with tx(conn):
        cur = conn.execute(
            """INSERT OR IGNORE INTO market_snapshots
               (id,symbol,venue,price,source,observed_at,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id("snap"), symbol, venue, price, source, observed_iso, iso()),
        )
        inserted = cur.rowcount > 0
    return {"symbol": symbol, "venue": venue, "price": price, "source": source,
            "observed_at": display_ts(observed_iso), "inserted": inserted}


def import_snapshots(conn, payload):
    """Import CSV or JSON export. Never invents prices: rejects rows missing provenance."""
    raw = payload.get("content")
    if not raw:
        raise ValueError("content is required (CSV or JSON text)")
    fmt = (payload.get("format") or "csv").lower()
    rows = []
    if fmt == "json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        rows = data if isinstance(data, list) else data.get("snapshots", [])
        if not isinstance(rows, list):
            raise ValueError("JSON must be a list of objects or {snapshots: [...]}")
    else:
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
    accepted, rejected = [], []
    for i, row in enumerate(rows, start=1):
        try:
            accepted.append(snapshot_add(conn, dict(row)))
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append({"row": i, "reason": str(exc)})
    return {"accepted": len(accepted), "rejected": rejected,
            "rows": accepted, "source_format": fmt}


def signal_add(conn, payload):
    require(payload, "symbol", "side", "source", "observed_at")
    side = str(payload["side"]).strip().lower()
    if side not in ("long", "short", "flat", "watch"):
        raise ValueError("side must be one of long, short, flat, watch")
    symbol = str(payload["symbol"]).strip().upper()[:64]
    venue = (payload.get("venue") or "unknown").strip().lower()[:64]
    observed = iso(parse_ts(payload["observed_at"], "observed_at"))
    sid = new_id("sig")
    with tx(conn):
        conn.execute(
            """INSERT INTO trading_signals
               (id,symbol,venue,side,confidence,rationale,source,observed_at,payload_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, symbol, venue, side, to_float(payload.get("confidence"), "confidence", None),
             payload.get("rationale"), str(payload["source"])[:200], observed,
             json.dumps(payload.get("payload") or {}, ensure_ascii=False), iso()),
        )
    return {"id": sid, "symbol": symbol, "side": side,
            "observed_at": display_ts(observed), "source": payload["source"],
            "disclaimer": DISCLAIMER}


DISCLAIMER = ("Analisis data, bukan rekomendasi investasi. NOVA tidak mengeksekusi order "
              "dan tidak menjamin hasil.")


# --------------------------------------------------------------------------- #
# journal + performance
# --------------------------------------------------------------------------- #
def journal_add(conn, payload):
    require(payload, "symbol", "side", "entry_price", "opened_at")
    side = str(payload["side"]).strip().lower()
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    entry = to_float(payload["entry_price"], "entry_price")
    if entry is None or entry <= 0:
        raise ValueError("entry_price must be positive")
    jid = new_id("jr")
    with tx(conn):
        conn.execute(
            """INSERT INTO trading_journal
               (id,symbol,venue,side,entry_price,exit_price,stop_loss,take_profit,size,fees,
                opened_at,closed_at,notes,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, str(payload["symbol"]).strip().upper()[:64],
             (payload.get("venue") or "unknown").strip().lower()[:64], side, entry,
             to_float(payload.get("exit_price"), "exit_price"),
             to_float(payload.get("stop_loss"), "stop_loss"),
             to_float(payload.get("take_profit"), "take_profit"),
             to_float(payload.get("size"), "size"),
             to_float(payload.get("fees"), "fees", 0.0),
             iso(parse_ts(payload["opened_at"], "opened_at")),
             iso(parse_ts(payload["closed_at"], "closed_at")) if payload.get("closed_at") else None,
             payload.get("notes"), iso()),
        )
    return {"id": jid}


def journal_close(conn, payload):
    require(payload, "id", "exit_price")
    exit_price = to_float(payload["exit_price"], "exit_price")
    if exit_price is None or exit_price <= 0:
        raise ValueError("exit_price must be positive")
    with tx(conn):
        cur = conn.execute(
            "UPDATE trading_journal SET exit_price=?, closed_at=?, notes=COALESCE(?,notes) WHERE id=?",
            (exit_price, iso(parse_ts(payload["closed_at"], "closed_at")) if payload.get("closed_at") else iso(),
             payload.get("notes"), payload["id"]),
        )
    if cur.rowcount == 0:
        raise LookupError(f"journal entry not found: {payload['id']}")
    return {"id": payload["id"], "exit_price": exit_price, "closed": True}


def _r_multiple(row) -> float | None:
    if row["exit_price"] is None or not row["stop_loss"]:
        return None
    risk = abs(row["entry_price"] - row["stop_loss"])
    if risk == 0:
        return None
    reward = (row["exit_price"] - row["entry_price"]) if row["side"] == "long" else (
        row["entry_price"] - row["exit_price"])
    return reward / risk


def journal_list(conn, payload):
    rows = conn.execute(
        "SELECT * FROM trading_journal ORDER BY opened_at DESC LIMIT ?",
        (to_int(payload.get("limit"), "limit", 30, 1, 200),),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "symbol": r["symbol"], "side": r["side"],
            "entry_price": r["entry_price"], "exit_price": r["exit_price"],
            "r_multiple": round(_r_multiple(r), 2) if _r_multiple(r) is not None else None,
            "opened_at": display_ts(r["opened_at"]), "closed_at": display_ts(r["closed_at"]),
        })
    return {"entries": out, "count": len(out)}


def performance(conn, payload):
    rows = conn.execute(
        "SELECT * FROM trading_journal WHERE closed_at IS NOT NULL"
    ).fetchall()
    if not rows:
        return {"status": "no_data", "message": "Belum ada trade tertutup; metrik tidak dihitung.",
                "disclaimer": DISCLAIMER}
    rs, wins, gross_win, gross_loss = [], 0, 0.0, 0.0
    for r in rows:
        rmult = _r_multiple(r)
        fees = r["fees"] or 0.0
        if rmult is not None:
            rs.append(rmult)
            if rmult > 0:
                wins += 1
                gross_win += rmult
            else:
                gross_loss += abs(rmult)
        elif r["exit_price"] is not None:
            pnl = ((r["exit_price"] - r["entry_price"]) if r["side"] == "long"
                   else (r["entry_price"] - r["exit_price"]))
            pnl -= fees
            if pnl > 0:
                wins += 1
                gross_win += pnl
            else:
                gross_loss += abs(pnl)
    trades = len(rows)
    return {
        "status": "ok",
        "trades": trades,
        "win_rate": round(wins / trades, 3),
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "with_r_multiple": len(rs),
        "disclaimer": DISCLAIMER,
        "note": "Metrik hanya dari trade tertutup di jurnal NOVA; data tidak lengkap menghasilkan nilai terbatas.",
    }


def price_alerts_due(conn, payload):
    """Watchlist rows whose latest snapshot crossed a configured note threshold (none by default)."""
    return {"status": "not_configured",
            "message": "Alert harga memerlukan threshold yang dikonfigurasi pengguna.",
            "watchlist": watch_list(conn, {})["watchlist"]}


ACTIONS = {
    "watch.add": watch_add,
    "watch.list": watch_list,
    "snapshot.add": snapshot_add,
    "import.snapshots": import_snapshots,
    "signal.add": signal_add,
    "journal.add": journal_add,
    "journal.close": journal_close,
    "journal.list": journal_list,
    "performance": performance,
    "alerts.due": price_alerts_due,
}
