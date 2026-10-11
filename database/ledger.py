"""Receivables and payables stored in SQLite."""
import logging
from typing import Tuple

import pandas as pd

from database.db import get_connection

logger = logging.getLogger(__name__)

# kind -> (table name, name of the party column). Fixed list, so no SQL injection is possible.
TABLES = {"receivable": ("receivables", "customer"), "payable": ("payables", "supplier")}
COLUMNS = ["id", "party", "amount", "amount_paid", "invoice_date", "due_date", "status"]
EXTRA_COLUMNS = [("invoice_date", "TEXT"), ("amount_paid", "REAL DEFAULT 0")]


def _table(kind: str):
    if kind not in TABLES:
        raise ValueError(f"Unknown ledger type: {kind}")
    return TABLES[kind]


def _ensure(conn) -> None:
    """Add the new columns to old tables (only if they are missing)."""
    for table, _ in TABLES.values():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue
        for column, definition in EXTRA_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_columns() -> None:
    with get_connection() as conn:
        _ensure(conn)


def add_entry(kind: str, party: str, amount, invoice_date, due_date) -> int:
    """Save one receivable/payable. Raises ValueError with a friendly message if input is bad."""
    party = str(party).strip()
    if not party:
        raise ValueError("Please enter a name.")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number.")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    invoice = pd.to_datetime(invoice_date, errors="coerce")
    due = pd.to_datetime(due_date, errors="coerce")
    if pd.isna(due):
        raise ValueError("Please enter a valid due date.")
    if not pd.isna(invoice) and due < invoice:
        raise ValueError("The due date cannot be before the invoice date.")

    table, party_column = _table(kind)
    with get_connection() as conn:
        _ensure(conn)
        cursor = conn.execute(
            f"""INSERT INTO {table} (business_id, {party_column}, amount, amount_paid,
                                     invoice_date, due_date, status)
                VALUES (1, ?, ?, 0, ?, ?, 'Open')""",
            (party, amount, None if pd.isna(invoice) else str(invoice.date()), str(due.date())))
        return int(cursor.lastrowid)


def list_entries(kind: str) -> pd.DataFrame:
    table, party_column = _table(kind)
    with get_connection() as conn:
        _ensure(conn)
        return pd.read_sql_query(
            f"""SELECT id, {party_column} AS party, amount, COALESCE(amount_paid, 0) AS amount_paid,
                       invoice_date, due_date, status
                FROM {table} WHERE business_id = 1 ORDER BY due_date, id""", conn)


def record_payment(kind: str, entry_id: int, payment) -> Tuple[float, str]:
    """Record a (part) payment. Returns (total_paid_so_far, new_status)."""
    try:
        payment = float(payment)
    except (TypeError, ValueError):
        raise ValueError("Payment must be a number.")
    if payment <= 0:
        raise ValueError("Payment must be greater than zero.")
    table, _ = _table(kind)
    with get_connection() as conn:
        _ensure(conn)
        row = conn.execute(f"SELECT amount, COALESCE(amount_paid, 0) FROM {table} WHERE id = ?",
                           (int(entry_id),)).fetchone()
        if row is None:
            raise ValueError("That entry was not found.")
        amount, paid = row
        still_due = amount - paid
        if payment > still_due + 0.005:
            raise ValueError(f"The payment is more than the amount still due ({still_due:,.0f}).")
        new_paid = round(paid + payment, 2)
        status = "Paid" if new_paid >= amount - 0.005 else "Open"
        conn.execute(f"UPDATE {table} SET amount_paid = ?, status = ? WHERE id = ?",
                     (new_paid, status, int(entry_id)))
        return new_paid, status


def delete_entry(kind: str, entry_id: int) -> None:
    table, _ = _table(kind)
    with get_connection() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (int(entry_id),))
