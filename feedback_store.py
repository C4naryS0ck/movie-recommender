"""
feedback_store.py - Tiny SQLite store for visitor feedback and anonymous usage events.

Roles
-----
- Visitors (no account): can ADD feedback and see only reviews an admin has featured.
- Admin (signed in with Google, email allow-listed in secrets): can read, feature,
  archive and delete feedback, and see anonymous usage stats.

Nothing personal is stored: no IP addresses, no emails from visitors. The optional
"name" field is whatever the visitor chooses to type.

Note: on Streamlit Community Cloud the disk is wiped when the app restarts or
redeploys. That's fine while testing; before you rely on it, point DB_PATH at a
persistent disk or swap these functions for a hosted DB (e.g. Supabase). Only this
file would need to change.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("FEEDBACK_DB", Path(__file__).resolve().parent / "data" / "feedback.db"))
STATUSES = ("new", "read", "featured", "archived")
MAX_MESSAGE = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL    NOT NULL,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    tags       TEXT    NOT NULL DEFAULT '[]',
    message    TEXT    NOT NULL DEFAULT '',
    name       TEXT    NOT NULL DEFAULT '',
    status     TEXT    NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL    NOT NULL,
    kind       TEXT    NOT NULL,   -- pick | describe | search_miss
    value      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind);
"""


@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


# ---- visitors -------------------------------------------------------------------------
def add_feedback(rating: int, tags: list[str], message: str, name: str = "") -> int:
    """Validate on the server too: widget limits are only enforced in the browser."""
    rating = int(rating)
    if not 1 <= rating <= 5:
        raise ValueError("rating must be 1-5")
    message = (message or "").strip()[:MAX_MESSAGE]
    name = (name or "").strip()[:40]
    tags = [str(t)[:40] for t in tags][:10]
    with _db() as con:
        cur = con.execute(
            "INSERT INTO feedback (created_at, rating, tags, message, name) VALUES (?, ?, ?, ?, ?)",
            (time.time(), rating, json.dumps(tags), message, name),
        )
        return int(cur.lastrowid)


def featured_feedback(limit: int = 6) -> list[dict]:
    """The only feedback visitors can see: reviews an admin chose to feature."""
    with _db() as con:
        rows = con.execute(
            "SELECT rating, message, name, created_at FROM feedback "
            "WHERE status = 'featured' AND message != '' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_event(kind: str, value: str) -> None:
    """Anonymous usage signal (which titles people pick, which searches find nothing)."""
    try:
        with _db() as con:
            con.execute("INSERT INTO events (created_at, kind, value) VALUES (?, ?, ?)",
                        (time.time(), kind, str(value)[:200]))
    except sqlite3.Error:
        pass  # analytics must never break the app


# ---- admin only ------------------------------------------------------------------------
def all_feedback(include_archived: bool = False) -> list[dict]:
    q = "SELECT * FROM feedback" + ("" if include_archived else " WHERE status != 'archived'")
    with _db() as con:
        rows = con.execute(q + " ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"])
        out.append(d)
    return out


def set_status(feedback_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with _db() as con:
        con.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, int(feedback_id)))


def delete_feedback(feedback_id: int) -> None:
    with _db() as con:
        con.execute("DELETE FROM feedback WHERE id = ?", (int(feedback_id),))


def top_events(kind: str, limit: int = 10) -> list[tuple[str, int]]:
    with _db() as con:
        rows = con.execute(
            "SELECT value, COUNT(*) AS n FROM events WHERE kind = ? "
            "GROUP BY value ORDER BY n DESC LIMIT ?", (kind, limit),
        ).fetchall()
    return [(r["value"], r["n"]) for r in rows]


def event_counts() -> dict[str, int]:
    with _db() as con:
        rows = con.execute("SELECT kind, COUNT(*) AS n FROM events GROUP BY kind").fetchall()
    return {r["kind"]: r["n"] for r in rows}
