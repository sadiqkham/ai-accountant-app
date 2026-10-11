"""Builds the full verified data block used by the chat and the dashboard summary."""
from datetime import date

from accounting import anomaly_detection as anomaly
from accounting import ledger_calc
from ai import explainer, insights
from database import crud, review_db
from database import ledger as ledger_db


def _ledger_block(summary: dict) -> dict:
    return {"total_due": summary["total_due"], "overdue_amount": summary["overdue_amount"],
            "overdue_entries": summary["overdue_count"], "open_entries": summary["open_count"],
            "oldest_overdue_days": summary["oldest_overdue_days"], "aging": summary["aging"],
            "largest_balances": summary["largest"]}


def build_full_context(data, currency: str) -> dict:
    """Profit/loss, expenses, cash, anomalies, receivables and payables, all calculated by Python."""
    try:
        settings = crud.get_numeric_settings()
        counts = review_db.counts()
    except Exception:
        settings, counts = {}, {}
    ctx = insights.build_context(data.all_data, data.period_data, data.start, data.end,
                                 data.label, currency, settings, counts)

    result = anomaly.detect_anomalies(data.all_data, currency)
    flags = anomaly.filter_flags_by_period(result.flags, data.start, data.end)
    ctx = explainer.add_anomaly_context(ctx, flags)

    today = date.today()
    notes = [n for n in ctx["data_notes"] if "Receivables and payables are not available" not in n]
    notes.append("Receivables and payables come from entries typed into the app's ledger. "
                 "They are not derived from the transaction list.")
    for key, kind, label in (("receivables", "receivable", "receivable"), ("payables", "payable", "payable")):
        try:
            summary = ledger_calc.summarize(ledger_calc.prepare_ledger(ledger_db.list_entries(kind), today))
            ctx[key] = _ledger_block(summary)
            if summary["open_count"] == 0:
                notes.append(f"No {label}s are recorded, so a total of 0 means nothing was entered.")
        except Exception:
            ctx[key] = None
    ctx["data_notes"] = notes
    return ctx
