"""Database actions for the review screen."""
import logging
from typing import Dict, List, Tuple

from database.db import get_connection

logger = logging.getLogger(__name__)
VALID_STATUSES = {"Pending", "Confirmed", "Rejected"}


def _marks(count: int) -> str:
    return ",".join("?" * count)


def apply_ai_categories(items: List[Tuple[int, str, str, str, float]]) -> int:
    """items = (id, type, category, subcategory, confidence).
    SAFETY: only rows with an EMPTY category are changed, so a category you chose is never overwritten."""
    if not items:
        return 0
    with get_connection() as conn:
        before = conn.total_changes
        conn.executemany(
            """UPDATE transactions
               SET transaction_type = CASE WHEN transaction_type IS NULL
                       OR transaction_type IN ('', 'Unknown') THEN ? ELSE transaction_type END,
                   category = ?, subcategory = ?, ai_confidence = ?
               WHERE id = ? AND (category IS NULL OR category = '')""",
            [(t, c, s, conf, i) for i, t, c, s, conf in items])
        return conn.total_changes - before


def set_status(ids: List[int], status: str) -> int:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE transactions SET status = ? WHERE id IN ({_marks(len(ids))})",
                              [status] + ids)
        return cursor.rowcount


def save_and_confirm(rows: List[Tuple[int, str, str, str]]) -> int:
    """rows = (id, type, category, subcategory). Saves your choice and confirms the row.
    If you changed the category, the old AI confidence is cleared (it no longer applies)."""
    if not rows:
        return 0
    with get_connection() as conn:
        before = conn.total_changes
        conn.executemany(
            """UPDATE transactions
               SET ai_confidence = CASE WHEN category = ? THEN ai_confidence ELSE NULL END,
                   transaction_type = ?, category = ?, subcategory = ?, status = 'Confirmed'
               WHERE id = ?""",
            [(cat, t, cat, sub, i) for i, t, cat, sub in rows])
        return conn.total_changes - before


def reclassify(ids: List[int]) -> int:
    """Clear the category and send the rows back to Pending so they can be categorized again."""
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    with get_connection() as conn:
        cursor = conn.execute(
            f"""UPDATE transactions SET category = '', subcategory = '', ai_confidence = NULL,
                status = 'Pending' WHERE id IN ({_marks(len(ids))})""", ids)
        return cursor.rowcount


def accept_high_confidence(min_confidence: float) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE transactions SET status = 'Confirmed'
               WHERE status = 'Pending' AND category IS NOT NULL AND category != ''
                 AND ai_confidence IS NOT NULL AND ai_confidence >= ?""", (min_confidence,))
        return cursor.rowcount


def counts() -> Dict[str, int]:
    keys = ["pending_uncategorized", "pending_categorized", "confirmed", "rejected"]
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN status = 'Pending' AND (category IS NULL OR category = '') THEN 1 ELSE 0 END),
                 SUM(CASE WHEN status = 'Pending' AND category IS NOT NULL AND category != '' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN status = 'Confirmed' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END)
               FROM transactions""").fetchone()
    return dict(zip(keys, [int(x or 0) for x in row]))
