"""
utils/memory_manager.py
-----------------------
SQLite-backed longitudinal patient memory store with full CRUD.
v2: All operations are scoped to a specific user_id.

Table: memory_entries
  id, user_id, category, fact, created_at, updated_at, source
"""

import logging
from datetime import datetime
from typing import List, Optional

from database import get_connection
from models.schemas import MemoryEntry, MEMORY_CATEGORIES

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    CRUD interface over the memory_entries SQLite table.
    Every method requires a user_id — no cross-user data leakage is possible.
    """

    # ── Public CRUD ───────────────────────────────────────────────────────

    def get_all(self, user_id: str) -> List[MemoryEntry]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [MemoryEntry(**{k: row[k] for k in row.keys() if k != "user_id"}) for row in rows]

    def get_by_id(self, entry_id: str, user_id: str) -> Optional[MemoryEntry]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return MemoryEntry(**{k: row[k] for k in row.keys() if k != "user_id"})

    def add(
        self,
        user_id: str,
        category: str,
        fact: str,
        source: str = "manual",
    ) -> MemoryEntry:
        cat = category.upper() if category.upper() in MEMORY_CATEGORIES else "GENERAL"
        entry = MemoryEntry(category=cat, fact=fact.strip(), source=source)
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO memory_entries
                   (id, user_id, category, fact, created_at, updated_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id, user_id, entry.category, entry.fact,
                    entry.created_at, entry.updated_at, entry.source,
                ),
            )
            conn.commit()
        logger.info("[MEMORY ADD] user=%s [%s] %s", user_id[:8], entry.category, entry.fact)
        return entry

    def batch_add(
        self,
        entries: List[dict],
        user_id: str,
        source: str = "auto",
    ) -> List[MemoryEntry]:
        """Add multiple entries atomically for a specific user."""
        added: List[MemoryEntry] = []
        rows = []
        for e in entries:
            fact = e.get("fact", "").strip()
            if not fact:
                continue
            cat_raw = e.get("category", "GENERAL")
            cat = cat_raw.upper() if cat_raw.upper() in MEMORY_CATEGORIES else "GENERAL"
            entry = MemoryEntry(category=cat, fact=fact, source=source)
            rows.append((
                entry.id, user_id, entry.category, entry.fact,
                entry.created_at, entry.updated_at, entry.source,
            ))
            added.append(entry)
            logger.info("[MEMORY AUTO] user=%s [%s] %s", user_id[:8], entry.category, entry.fact)

        if rows:
            with get_connection() as conn:
                conn.executemany(
                    """INSERT INTO memory_entries
                       (id, user_id, category, fact, created_at, updated_at, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                conn.commit()
        return added

    def update(
        self,
        entry_id: str,
        user_id: str,
        category: Optional[str],
        fact: Optional[str],
    ) -> Optional[MemoryEntry]:
        now = datetime.now().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            ).fetchone()
            if row is None:
                return None

            new_cat = row["category"]
            new_fact = row["fact"]

            if category is not None:
                new_cat = (
                    category.upper()
                    if category.upper() in MEMORY_CATEGORIES
                    else "GENERAL"
                )
            if fact is not None:
                new_fact = fact.strip()

            conn.execute(
                """UPDATE memory_entries
                   SET category = ?, fact = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (new_cat, new_fact, now, entry_id, user_id),
            )
            conn.commit()
            updated_row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?", (entry_id,)
            ).fetchone()

        logger.info("[MEMORY UPDATE] id=%s user=%s", entry_id, user_id[:8])
        return MemoryEntry(**{k: updated_row[k] for k in updated_row.keys() if k != "user_id"})

    def delete(self, entry_id: str, user_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            )
            conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("[MEMORY DELETE] id=%s user=%s", entry_id, user_id[:8])
        return deleted

    def as_context_string(self, user_id: str) -> str:
        """Format this user's full memory as a plain-text block for LLM prompts."""
        entries = self.get_all(user_id=user_id)
        if not entries:
            return "(No patient memory entries yet.)"
        lines = ["PATIENT LONGITUDINAL HEALTH MEMORY", "=" * 50]
        for e in entries:
            ts = e.created_at[:16].replace("T", " ")
            lines.append(f"[{ts}] [{e.category}] {e.fact}")
        return "\n".join(lines)