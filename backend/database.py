"""
database.py
-----------
SQLite initialisation and connection management.
All tables are created here; other modules import get_connection to run queries.

v2: Adds users, otp_codes tables and user_id foreign key to documents,
    memory_entries, and chat_sessions.
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import settings

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create all tables if they don't already exist, and run safe migrations."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            -- ── Auth ──────────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS users (
                id              TEXT PRIMARY KEY,
                email           TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                is_verified     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS otp_codes (
                id          TEXT PRIMARY KEY,
                email       TEXT NOT NULL,
                otp_code    TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                used        INTEGER NOT NULL DEFAULT 0
            );

            -- ── Documents ─────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS documents (
                id               TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                filename         TEXT NOT NULL,
                uploaded_at      TEXT NOT NULL,
                chunk_count      INTEGER NOT NULL,
                char_count       INTEGER NOT NULL,
                core_content     TEXT,
                doctor_concerned TEXT,
                date_time        TEXT,
                document_type    TEXT
            );

            CREATE TABLE IF NOT EXISTS document_faiss_indices (
                document_id  TEXT NOT NULL
                             REFERENCES documents(id) ON DELETE CASCADE,
                faiss_index  INTEGER NOT NULL
            );

            -- ── Memory ────────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS memory_entries (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category    TEXT NOT NULL,
                fact        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT,
                source      TEXT NOT NULL DEFAULT 'manual'
            );

            -- ── Chat ──────────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title       TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL
                            REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                metadata    TEXT
            );
        """)
        conn.commit()

    # ── Safe migrations for pre-existing databases ─────────────────────────
    # If upgrading from v1 (no user_id columns), add them non-destructively.
    _run_migrations()

    logger.info("SQLite database ready → %s", settings.db_path)


def _run_migrations() -> None:
    """Add user_id columns to legacy tables if they don't exist yet."""
    migrations = [
        ("documents",      "ALTER TABLE documents ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'"),
        ("memory_entries", "ALTER TABLE memory_entries ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'"),
        ("chat_sessions",  "ALTER TABLE chat_sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'"),
    ]
    with get_connection() as conn:
        for table, sql in migrations:
            existing_cols = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "user_id" not in existing_cols:
                try:
                    conn.execute(sql)
                    conn.commit()
                    logger.info("Migration applied: added user_id to %s", table)
                except sqlite3.OperationalError as exc:
                    logger.warning("Migration skipped for %s: %s", table, exc)


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Yield an open SQLite connection; always closes on exit."""
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()