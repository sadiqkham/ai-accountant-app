"""SQLite storage. All tables are created automatically."""
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Set

import pandas as pd

from utils.helpers import transaction_key

logger = logging.getLogger(__name__)

# Colab files disappear when the runtime resets.
# To keep data, set AI_ACCOUNTANT_DB to a Google Drive path BEFORE starting the app.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("AI_ACCOUNTANT_DB", os.path.join(PROJECT_ROOT, "data", "accountant.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY, business_name TEXT, business_type TEXT, industry TEXT,
    city TEXT, currency TEXT DEFAULT 'PKR', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER DEFAULT 1,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    transaction_type TEXT,
    payment_method TEXT,
    party TEXT,
    category TEXT,
    subcategory TEXT,
    ai_confidence REAL,
    status TEXT DEFAULT 'Pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS receivables (
    id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER DEFAULT 1,
    customer TEXT, amount REAL, due_date TEXT, status TEXT DEFAULT 'Open'
);
CREATE TABLE IF NOT EXISTS payables (
    id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER DEFAULT 1,
    supplier TEXT, amount REAL, due_date TEXT, status TEXT DEFAULT 'Open'
);
"""


class DatabaseError(Exception):
    """A database problem we can explain to the user."""


@contextmanager
def get_connection():
    """Open the database, save changes if all went well, undo if not."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("Database error: %s", exc)
        raise DatabaseError(f"Database problem: {exc}") from exc
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist (safe to call many times)."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO businesses (id, business_name) VALUES (1, 'My Business')")


def insert_transactions(df: pd.DataFrame, status: str = "Pending", business_id: int = 1) -> int:
    """Save validated transactions. Returns how many rows were saved."""
    if df is None or df.empty:
        return 0
    rows = [(business_id, r.Date, r.Description, float(r.Amount), r.Type,
             r.Payment_Method, r.Party, r.Category, status)
            for r in df.itertuples(index=False)]
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO transactions
               (business_id, date, description, amount, transaction_type,
                payment_method, party, category, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    logger.info("Saved %d transactions", len(rows))
    return len(rows)


def get_transactions(business_id: int = 1) -> pd.DataFrame:
    """Return all saved transactions (empty table if none)."""
    with get_connection() as conn:
        return pd.read_sql_query(
            """SELECT id, date, description, amount, transaction_type, payment_method,
                      party, category, subcategory, ai_confidence, status
               FROM transactions WHERE business_id = ? ORDER BY date, id""",
            conn, params=(business_id,))


def count_transactions() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def get_existing_keys() -> Set[str]:
    """Fingerprints of saved transactions, used to detect duplicates."""
    with get_connection() as conn:
        rows = conn.execute("SELECT date, description, amount, party FROM transactions").fetchall()
    return {transaction_key(d, desc, amt, party) for d, desc, amt, party in rows}


def delete_all_transactions() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions")
    logger.info("All transactions deleted")
