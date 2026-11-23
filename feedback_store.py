"""
feedback_store.py - Storage for visitor feedback and anonymous usage events.

Backends
--------
- Supabase (PostgreSQL) when a database URL is configured, so data survives restarts:
      # .streamlit/secrets.toml          (or env var DATABASE_URL)
      [database]
      url = "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
- SQLite file (data/feedback.db) otherwise: handy for local testing.

Roles
-----
- Visitors (no account): can ADD feedback and see only reviews an admin has featured.
- Admin (Google sign-in, allow-listed email): can read, feature, archive and delete feedback,
  and see anonymous usage stats.

Nothing personal is stored: no IP addresses, no emails from visitors. The optional "name"
field is whatever the visitor chooses to type.

Command line
------------
    python feedback_store.py check     # which backend is active + row counts
    python feedback_store.py migrate   # create Supabase tables, copy local SQLite rows into them
"""
from __future__ import annotations

import atexit
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SQLITE_PATH = Path(os.environ.get("FEEDBACK_DB", Path(__file__).resolve().parent / "data" / "feedback.db"))
STATUSES = ("new", "read", "featured", "archived")
MAX_MESSAGE = 1000

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), tags TEXT NOT NULL DEFAULT '[]',
    message TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind);
"""

# Row Level Security ON with no policies = Supabase's public REST API (anon key) can't read or
# write these tables. The app connects as the database owner, which RLS doesn't restrict.
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), tags TEXT NOT NULL DEFAULT '[]',
    message TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL,
    kind TEXT NOT NULL, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind);
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
"""


# ---- connection plumbing -----------------------------------------------------------------
def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st

            url = st.secrets.get("database", {}).get("url")
        except Exception:  # no secrets file
            url = None
    # ignore placeholders like "PASTE_..." so an unfinished secrets file can't break the app
    return url if url and url.startswith(("postgresql://", "postgres://")) else None


def backend() -> str:
    return "supabase" if _database_url() else "sqlite"


_pool = None
_pool_lock = threading.Lock()


def _pg_pool():
    """One small connection pool per process, created on first use (schema made once)."""
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                _database_url(), min_size=1, max_size=4, open=True, timeout=15,
                check=ConnectionPool.check_connection,  # drop connections the server closed
                kwargs={"row_factory": dict_row, "connect_timeout": 10,
                        "prepare_threshold": None},  # safe with Supabase's connection pooler
            )
            atexit.register(_pool.close)  # close cleanly before Python shuts down
            with _pool.connection() as con:
                con.execute(_PG_SCHEMA)
    return _pool


@contextmanager
def _db():
    """Yields (connection, is_postgres). Commits on success."""
    if _database_url():
        with _pg_pool().connection() as con:  # pool commits on exit, rolls back on error
            yield con, True
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(SQLITE_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            con.executescript(_SQLITE_SCHEMA)
            yield con, False
            con.commit()
        finally:
            con.close()


def _q(sql: str, is_pg: bool) -> str:
    """Queries are written with SQLite's ? placeholders; PostgreSQL wants %s."""
    return sql.replace("?", "%s") if is_pg else sql


def _rows(con, is_pg: bool, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(_q(sql, is_pg), params).fetchall()]


# ---- visitors -------------------------------------------------------------------------
def add_feedback(rating: int, tags: list[str], message: str, name: str = "",
                 created_at: float | None = None, status: str = "new") -> int:
    """Validate on the server too: widget limits are only enforced in the browser."""
    rating = int(rating)
    if not 1 <= rating <= 5:
        raise ValueError("rating must be 1-5")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    message = (message or "").strip()[:MAX_MESSAGE]
    name = (name or "").strip()[:40]
    tags = [str(t)[:40] for t in tags][:10]
    params = (created_at or time.time(), rating, json.dumps(tags), message, name, status)
    sql = "INSERT INTO feedback (created_at, rating, tags, message, name, status) VALUES (?, ?, ?, ?, ?, ?)"
    with _db() as (con, pg):
        if pg:
            return int(con.execute(_q(sql + " RETURNING id", pg), params).fetchone()["id"])
        return int(con.execute(sql, params).lastrowid)


def featured_feedback(limit: int = 6) -> list[dict]:
    """The only feedback visitors can see: reviews an admin chose to feature."""
    with _db() as (con, pg):
        return _rows(con, pg, "SELECT rating, message, name, created_at FROM feedback "
                              "WHERE status = 'featured' AND message != '' ORDER BY created_at DESC LIMIT ?",
                     (limit,))


def log_event(kind: str, value: str) -> None:
    """Anonymous usage signal (which titles people pick, which searches find nothing)."""
    try:
        with _db() as (con, pg):
            con.execute(_q("INSERT INTO events (created_at, kind, value) VALUES (?, ?, ?)", pg),
                        (time.time(), kind, str(value)[:200]))
    except Exception:
        pass  # analytics must never break the app


# ---- admin only ------------------------------------------------------------------------
def all_feedback(include_archived: bool = False) -> list[dict]:
    q = "SELECT * FROM feedback" + ("" if include_archived else " WHERE status != 'archived'")
    with _db() as (con, pg):
        rows = _rows(con, pg, q + " ORDER BY created_at DESC")
    for r in rows:
        r["tags"] = json.loads(r["tags"])
    return rows


def set_status(feedback_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with _db() as (con, pg):
        con.execute(_q("UPDATE feedback SET status = ? WHERE id = ?", pg), (status, int(feedback_id)))


def delete_feedback(feedback_id: int) -> None:
    with _db() as (con, pg):
        con.execute(_q("DELETE FROM feedback WHERE id = ?", pg), (int(feedback_id),))


def top_events(kind: str, limit: int = 10) -> list[tuple[str, int]]:
    with _db() as (con, pg):
        rows = _rows(con, pg, "SELECT value, COUNT(*) AS n FROM events WHERE kind = ? "
                              "GROUP BY value ORDER BY n DESC LIMIT ?", (kind, limit))
    return [(r["value"], int(r["n"])) for r in rows]


def event_counts() -> dict[str, int]:
    with _db() as (con, pg):
        rows = _rows(con, pg, "SELECT kind, COUNT(*) AS n FROM events GROUP BY kind")
    return {r["kind"]: int(r["n"]) for r in rows}


# ---- command line ---------------------------------------------------------------------
def _sqlite_rows(table: str) -> list[dict]:
    if not SQLITE_PATH.exists():
        return []
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id")]
    except sqlite3.OperationalError:  # table never created
        return []
    finally:
        con.close()


def _main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    print(f"backend: {backend()}")
    if cmd == "migrate":
        if backend() != "supabase":
            raise SystemExit("No database URL found. Add [database] url to .streamlit/secrets.toml first.")
        fb_rows, ev_rows = _sqlite_rows("feedback"), _sqlite_rows("events")
        with _db() as (con, pg):
            existing = con.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
        if existing and fb_rows:
            raise SystemExit(f"Supabase already has {existing} reviews; not copying again (avoids duplicates).")
        for r in fb_rows:
            add_feedback(r["rating"], json.loads(r["tags"]), r["message"], r["name"],
                         created_at=r["created_at"], status=r["status"])
        with _db() as (con, pg):
            for r in ev_rows:
                con.execute("INSERT INTO events (created_at, kind, value) VALUES (%s, %s, %s)",
                            (r["created_at"], r["kind"], r["value"]))
        print(f"copied {len(fb_rows)} reviews and {len(ev_rows)} events from {SQLITE_PATH.name}")
    print(f"reviews: {len(all_feedback(include_archived=True))} | events: {event_counts()}")


if __name__ == "__main__":
    _main()
