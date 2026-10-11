"""Dashboard alerts. Every alert comes from calculated numbers, not from AI."""
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd


def pct_change(new, old) -> Optional[float]:
    """Percentage change from old to new (None if old is zero or missing)."""
    if old is None or pd.isna(old) or old == 0:
        return None
    return (new - old) / abs(old) * 100


def comparison_months(monthly: pd.DataFrame, today: date) -> Optional[Tuple[str, str]]:
    """The two most recent COMPLETED months (the current month is still in progress)."""
    months = monthly["month"].tolist()
    current = today.strftime("%Y-%m")
    if months and months[-1] == current:
        months = months[:-1]
    if len(months) < 2:
        return None
    return months[-2], months[-1]


def build_alerts(pl: Dict, monthly: pd.DataFrame, flags: pd.DataFrame, receivables: Dict,
                 payables: Dict, review_counts: Dict, cash: Dict, today: date,
                 currency: str, include_pending: bool = False) -> List[Dict]:
    alerts: List[Dict] = []
    money = lambda x: f"{currency} {x:,.0f}"

    def add(level: str, text: str) -> None:
        alerts.append({"level": level, "text": text})

    if pl["net_profit"] < 0:
        add("error", f"Net loss of {money(abs(pl['net_profit']))} in this period: expenses "
                     f"({money(pl['total_expenses'])}) are higher than revenue ({money(pl['total_revenue'])}).")

    months = comparison_months(monthly, today)
    if months:
        previous, latest = months
        rows = monthly.set_index("month")
        expense_change = pct_change(rows.at[latest, "expenses"], rows.at[previous, "expenses"])
        revenue_change = pct_change(rows.at[latest, "revenue"], rows.at[previous, "revenue"])
        if expense_change is not None and expense_change >= 10 and (revenue_change is None or expense_change > revenue_change):
            tail = f" while revenue changed {revenue_change:+.1f}%." if revenue_change is not None else "."
            add("warning", f"Expenses grew {expense_change:.1f}% from {previous} to {latest}{tail}")

    if cash.get("closing") is None:
        add("info", "Opening cash is not set, so the cash balance cannot be shown. Add it in Settings.")
    elif cash["closing"] < 0:
        add("error", f"The cash balance is negative ({money(cash['closing'])}).")

    high = int((flags["risk_level"] == "High").sum()) if not flags.empty else 0
    if high:
        add("warning", f"{high} high-risk transaction(s) need review (see Anomaly Detection). "
                       "A flag does not mean fraud.")
    if receivables.get("overdue_count"):
        add("warning", f"{receivables['overdue_count']} overdue receivable(s) totalling "
                       f"{money(receivables['overdue_amount'])}. Consider following up with those customers.")
    if payables.get("overdue_count"):
        add("warning", f"{payables['overdue_count']} overdue payable(s) totalling "
                       f"{money(payables['overdue_amount'])}. Check the payment deadlines with those suppliers.")

    pending = review_counts.get("pending_uncategorized", 0) + review_counts.get("pending_categorized", 0)
    if pending and not include_pending:
        add("info", f"{pending} transaction(s) are waiting for review and are not included in these numbers.")

    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a["level"]])
