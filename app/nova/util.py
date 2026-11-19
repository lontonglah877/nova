"""Shared helpers: ids, timestamps, JSON output, timezone."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
# Asia/Jakarta is UTC+7 with no DST. We do not depend on the tz database so the
# same code runs on a 1 GB container that may ship without tzdata.
JAKARTA = timezone(timedelta(hours=7), "Asia/Jakarta")


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    """UTC timestamp, second precision, trailing Z."""
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value, field="timestamp") -> datetime:
    """Parse ISO-8601 into an aware UTC datetime. Naive input is treated as Asia/Jakarta."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, UTC)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field}: not ISO-8601: {value!r}") from exc
    else:
        raise ValueError(f"{field}: expected ISO-8601 string, got {type(value).__name__}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JAKARTA)
    return dt.astimezone(UTC)


def display_ts(value) -> str | None:
    """UTC stored -> Asia/Jakarta display string."""
    if not value:
        return None
    try:
        dt = parse_ts(value)
    except ValueError:
        return str(value)
    return dt.astimezone(JAKARTA).strftime("%Y-%m-%d %H:%M WIB")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ok(data=None, **extra):
    payload = {"ok": True, "data": data if data is not None else {}}
    payload.update(extra)
    return payload


def fail(code: str, message: str, **extra):
    payload = {"ok": False, "error": {"code": code, "message": message}}
    payload["error"].update(extra)
    return payload


def emit(payload: dict, exit_code: int | None = None) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()
    if exit_code is not None:
        raise SystemExit(exit_code)


def read_payload(argv_payload: str | None) -> dict:
    """JSON from --args, else stdin when piped, else {}."""
    if argv_payload:
        text = argv_payload
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = ""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def require(payload: dict, *keys: str) -> None:
    missing = [k for k in keys if payload.get(k) in (None, "")]
    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))


def to_int(value, field: str, default=None, minimum=None, maximum=None):
    if value is None or value == "":
        return default
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: expected integer, got {value!r}") from exc
    if minimum is not None and out < minimum:
        raise ValueError(f"{field}: must be >= {minimum}")
    if maximum is not None and out > maximum:
        raise ValueError(f"{field}: must be <= {maximum}")
    return out


def to_float(value, field: str, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: expected number, got {value!r}") from exc


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
