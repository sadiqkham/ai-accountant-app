"""Deterministic accounting calculations. NO AI is used in this file."""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PERIODS = ["All time", "This month", "Last month", "This quarter", "Custom range"]
NON_CASH_METHODS = {"credit"}   # money did not move yet
DB_COLUMNS = ["id", "date", "description", "amount", "transaction_type", "payment_method",
              "party", "category", "subcategory", "ai_confidence", "status"]


# ------------------------------------------------------------ safe maths
def safe_divide(numerator, denominator) -> Optional[float]:
    """numerator / denominator, or None if it cannot be calculated (e.g. divide by zero)."""
    try:
        if numerator is None or denominator is None:
            return None
        if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
            return None
        return float(numerator) / float(denominator)
    except (TypeError, ValueError):
        return None


def percentage(numerator, denominator) -> Optional[float]:
    result = safe_divide(numerator, denominator)
    return None if result is None else result * 100


# ------------------------------------------------------------ preparing data
def prepare(raw: pd.DataFrame, include_pending: bool = False) -> pd.DataFrame:
    """Keep only Confirmed rows (plus Pending rows in preview mode) and tidy the columns."""
    if raw is None or raw.empty:
        raw = pd.DataFrame(columns=DB_COLUMNS)
    statuses = ["Confirmed"] + (["Pending"] if include_pending else [])
    df = raw[raw["status"].isin(statuses)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["transaction_type"] = df["transaction_type"].fillna("").replace("", "Unknown")
    df["payment_method"] = df["payment_method"].fillna("")
    df["category"] = df["category"].fillna("").replace("", "Uncategorized")
    df["month"] = df["date"].dt.to_period("M").astype(str)
    return df.reset_index(drop=True)


def get_period_dates(period: str, today: date, custom_start: Optional[date] = None,
                     custom_end: Optional[date] = None):
    """Return (start, end) as Timestamps, or (None, None) for 'All time'."""
    if period == "This month":
        start, end = today.replace(day=1), today
    elif period == "Last month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif period == "This quarter":
        first_month = 3 * ((today.month - 1) // 3) + 1
        start, end = date(today.year, first_month, 1), today
    elif period == "Custom range":
        start, end = custom_start, custom_end
    else:
        return None, None
    return pd.Timestamp(start), pd.Timestamp(end)


def filter_by_date(df: pd.DataFrame, start, end) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["date"] >= start
    if end is not None:
        mask &= df["date"] <= end
    return df[mask]


def describe_period(start, end) -> str:
    if start is None or end is None:
        return "All dates"
    return f"{start:%d %b %Y} to {end:%d %b %Y}"


def data_quality_notes(df: pd.DataFrame) -> List[str]:
    """Plain-language warnings about rows that affect the numbers."""
    notes = []
    unknown = int((df["transaction_type"] == "Unknown").sum())
    if unknown:
        notes.append(f"{unknown} transaction(s) have an unknown Type and are NOT included in any total.")
    balance_sheet = int(df["transaction_type"].isin(["Asset", "Liability"]).sum())
    if balance_sheet:
        notes.append(f"{balance_sheet} Asset/Liability transaction(s) are not part of the "
                     "Profit & Loss (they belong on a balance sheet).")
    pl_rows = df[df["transaction_type"].isin(["Income", "Expense"])]
    uncategorized = int((pl_rows["category"] == "Uncategorized").sum())
    if uncategorized:
        notes.append(f"{uncategorized} transaction(s) have no category. They appear as "
                     "'Uncategorized' and ARE included in totals.")
    return notes


# ------------------------------------------------------------ profit and loss
def profit_and_loss(df: pd.DataFrame) -> Dict:
    income = df[df["transaction_type"] == "Income"]
    expense = df[df["transaction_type"] == "Expense"]
    revenue_by_category = income.groupby("category")["amount"].sum().sort_values(ascending=False)
    expense_by_category = expense.groupby("category")["amount"].sum().sort_values(ascending=False)
    total_revenue = round(float(revenue_by_category.sum()), 2)
    total_expenses = round(float(expense_by_category.sum()), 2)
    net_profit = round(total_revenue - total_expenses, 2)
    return {
        "revenue_by_category": revenue_by_category,
        "expense_by_category": expense_by_category,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "net_margin": percentage(net_profit, total_revenue),   # None when revenue is 0
    }


def format_pl_text(pl: Dict, currency: str, period_label: str) -> str:
    """Build the statement as plain text, like the example in your master prompt."""
    width = 46

    def line(label: str, amount: float) -> str:
        return f"{label:<28}{currency} {amount:>13,.0f}"

    lines = ["PROFIT & LOSS STATEMENT", f"Period: {period_label}", "", "Revenue"]
    for category, amount in pl["revenue_by_category"].items():
        lines.append(line(category, amount))
    lines += ["-" * width, line("Total Revenue", pl["total_revenue"]), "", "Expenses"]
    for category, amount in pl["expense_by_category"].items():
        lines.append(line(category, amount))
    lines += ["-" * width, line("Total Expenses", pl["total_expenses"]), "",
              line("Net Profit" if pl["net_profit"] >= 0 else "Net Loss", pl["net_profit"])]
    return "\n".join(lines)


# ------------------------------------------------------------ expense analysis
def expense_analysis(df: pd.DataFrame) -> Dict:
    expense = df[df["transaction_type"] == "Expense"]
    by_category = (expense.groupby("category")["amount"].agg(total="sum", transactions="count")
                   .sort_values("total", ascending=False).reset_index())
    total = float(by_category["total"].sum())
    by_category["percent"] = (by_category["total"] / total * 100) if total > 0 else 0.0
    monthly = expense.groupby("month")["amount"].sum().rename("total").reset_index()
    return {"total": round(total, 2), "by_category": by_category, "monthly": monthly}


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Revenue, expenses and profit for each month."""
    revenue = df[df["transaction_type"] == "Income"].groupby("month")["amount"].sum()
    expenses = df[df["transaction_type"] == "Expense"].groupby("month")["amount"].sum()
    out = pd.DataFrame({"revenue": revenue, "expenses": expenses}).fillna(0.0).sort_index()
    out["net_profit"] = out["revenue"] - out["expenses"]
    out.index.name = "month"
    return out.reset_index()


# ------------------------------------------------------------ cash flow
def _net_cash(frame: pd.DataFrame) -> float:
    inflow = frame.loc[frame["transaction_type"] == "Income", "amount"].sum()
    outflow = frame.loc[frame["transaction_type"] == "Expense", "amount"].sum()
    return float(inflow - outflow)


def cash_flow(df: pd.DataFrame, start, end, opening_cash: Optional[float]) -> Dict:
    """Opening + inflows - outflows = closing.
    opening_cash = balance BEFORE the first recorded transaction (None if unknown).
    Money moved before 'start' is added so the opening balance matches the chosen period."""
    is_pl = df["transaction_type"].isin(["Income", "Expense"])
    non_cash = df["payment_method"].str.strip().str.lower().isin(NON_CASH_METHODS)
    cash_rows = is_pl & ~non_cash

    in_period = pd.Series(True, index=df.index)
    if start is not None:
        in_period &= df["date"] >= start
    if end is not None:
        in_period &= df["date"] <= end

    period_cash = df[in_period & cash_rows].copy()
    before_cash = df[(df["date"] < start) & cash_rows] if start is not None else df.iloc[0:0]

    inflows = float(period_cash.loc[period_cash["transaction_type"] == "Income", "amount"].sum())
    outflows = float(period_cash.loc[period_cash["transaction_type"] == "Expense", "amount"].sum())
    net_change = inflows - outflows
    opening = None if opening_cash is None else float(opening_cash) + _net_cash(before_cash)
    closing = None if opening is None else opening + net_change

    def by_group(column: str) -> pd.DataFrame:
        grouped = (period_cash.groupby([column, "transaction_type"])["amount"].sum()
                   .unstack(fill_value=0).reindex(columns=["Income", "Expense"], fill_value=0))
        return grouped.rename(columns={"Income": "Inflow", "Expense": "Outflow"})

    monthly = by_group("month").rename(columns={"Inflow": "inflow", "Outflow": "outflow"})
    monthly["net"] = monthly["inflow"] - monthly["outflow"]
    monthly.index.name = "month"

    period_cash["payment_method"] = period_cash["payment_method"].replace("", "(not given)")
    return {
        "opening_cash": opening, "inflows": round(inflows, 2), "outflows": round(outflows, 2),
        "net_change": round(net_change, 2),
        "closing_cash": None if closing is None else round(closing, 2),
        "monthly": monthly.reset_index(),
        "by_method": by_group("payment_method").reset_index(),
        "excluded_credit": int((in_period & is_pl & non_cash).sum()),
        "excluded_balance_sheet": int((in_period & df["transaction_type"].isin(["Asset", "Liability"])).sum()),
    }
