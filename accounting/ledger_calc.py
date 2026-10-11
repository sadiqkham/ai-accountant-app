"""Receivable/payable calculations (days outstanding, status, aging). No AI here."""
from datetime import date
from typing import Dict

import pandas as pd

BUCKETS = ["Not yet due", "1-30 days overdue", "31-60 days overdue", "61+ days overdue"]


def _status(amount_due: float, due, today: pd.Timestamp) -> str:
    if amount_due <= 0:
        return "Paid"
    if pd.isna(due):
        return "No due date"
    days_left = (due - today).days
    if days_left < 0:
        return "Overdue"
    if days_left <= 7:
        return "Due soon"
    return "Not yet due"


def _bucket(days_overdue) -> str:
    if pd.isna(days_overdue) or days_overdue <= 0:
        return BUCKETS[0]
    if days_overdue <= 30:
        return BUCKETS[1]
    if days_overdue <= 60:
        return BUCKETS[2]
    return BUCKETS[3]


def prepare_ledger(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Add amount_due, days_outstanding, days_overdue, display_status and aging bucket."""
    out = df.copy()
    for column in ("amount", "amount_paid"):
        if column not in out.columns:
            out[column] = 0.0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    for column in ("due_date", "invoice_date"):
        if column not in out.columns:
            out[column] = None
    out["amount_due"] = (out["amount"] - out["amount_paid"]).clip(lower=0)
    due = pd.to_datetime(out["due_date"], errors="coerce")
    invoice = pd.to_datetime(out["invoice_date"], errors="coerce")
    today_ts = pd.Timestamp(today)
    out["days_outstanding"] = (today_ts - invoice).dt.days
    out["days_overdue"] = (today_ts - due).dt.days.clip(lower=0)
    out["display_status"] = [_status(a, d, today_ts) for a, d in zip(out["amount_due"], due)]
    out["bucket"] = [_bucket(d) for d in out["days_overdue"]]
    return out


def summarize(prepared: pd.DataFrame) -> Dict:
    """Totals and aging for the entries that still have money due."""
    open_rows = prepared[prepared["amount_due"] > 0]
    overdue = open_rows[open_rows["days_overdue"].fillna(0) > 0]
    aging = {b: round(float(open_rows.loc[open_rows["bucket"] == b, "amount_due"].sum()), 2) for b in BUCKETS}
    largest = open_rows.groupby("party")["amount_due"].sum().sort_values(ascending=False).head(5)
    return {
        "total_due": round(float(open_rows["amount_due"].sum()), 2),
        "overdue_amount": round(float(overdue["amount_due"].sum()), 2),
        "overdue_count": int(len(overdue)),
        "open_count": int(len(open_rows)),
        "oldest_overdue_days": int(overdue["days_overdue"].max()) if len(overdue) else 0,
        "aging": aging,
        "largest": [{"party": p, "amount_due": round(float(v), 2)} for p, v in largest.items()],
    }
