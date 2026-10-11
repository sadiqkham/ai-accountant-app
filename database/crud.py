"""Extra database functions: settings, applying categories, confirming."""
import logging
from typing import Dict, List, Optional, Tuple

from database.db import get_connection

logger = logging.getLogger(__name__)

SETTING_KEYS = ["opening_cash", "current_assets", "current_liabilities"]


def _ensure_settings_table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")


def get_numeric_settings() -> Dict[str, Optional[float]]:
    """Return each setting as a number, or None if it was never entered."""
    with get_connection() as conn:
        _ensure_settings_table(conn)
        saved = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    result: Dict[str, Optional[float]] = {}
    for key in SETTING_KEYS:
        try:
            result[key] = float(saved[key]) if key in saved else None
        except (TypeError, ValueError):
            result[key] = None
    return result


def set_numeric_setting(key: str, value: Optional[float]) -> None:
    """Save a number, or delete the setting when value is None."""
    if key not in SETTING_KEYS:
        raise ValueError(f"Unknown setting: {key}")
    with get_connection() as conn:
        _ensure_settings_table(conn)
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (key, str(float(value))))


def apply_rule_categories(suggestions: List[Tuple[int, str, str, str]]) -> int:
    """Each item is (id, type, category, subcategory).
    SAFETY: only rows whose category is EMPTY are changed, so a category chosen
    by the user is never overwritten. Type is filled only if it was 'Unknown'."""
    if not suggestions:
        return 0
    rows = [(t, c, s, i) for i, t, c, s in suggestions]
    with get_connection() as conn:
        before = conn.total_changes
        conn.executemany(
            """UPDATE transactions
               SET transaction_type = CASE
                       WHEN transaction_type IS NULL OR transaction_type IN ('', 'Unknown')
                       THEN ? ELSE transaction_type END,
                   category = ?, subcategory = ?
               WHERE id = ? AND (category IS NULL OR category = '')""",
            [(t, c, s, i) for t, c, s, i in rows])
        changed = conn.total_changes - before
    logger.info("Categories applied to %d rows", changed)
    return changed


def confirm_categorized() -> int:
    """TESTING SHORTCUT: mark every Pending row that has a category as Confirmed."""
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE transactions SET status = 'Confirmed'
               WHERE status = 'Pending' AND category IS NOT NULL AND category != ''""")
        return cursor.rowcount
