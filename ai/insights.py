"""Builds the VERIFIED data block, then asks the AI to explain it."""
import json
import logging
import re
from datetime import date
from typing import Callable, Dict, List, Optional

import pandas as pd

from accounting import calculations as calc
from accounting import trends
from ai import groq_client
from ai.prompts import ANALYST_SYSTEM, CHAT_SYSTEM

logger = logging.getLogger(__name__)


def _f(value, digits: int = 2):
    """Plain Python number (or None) so the data block can be turned into JSON."""
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


# ---------------------------------------------------------------- 1. verified data
def build_context(all_df: pd.DataFrame, period_df: pd.DataFrame, start, end, label: str,
                  currency: str, settings: Dict, review_counts: Optional[Dict] = None,
                  today: Optional[date] = None) -> Dict:
    """Everything here was calculated by Python. This is the ONLY data the AI may use."""
    today = today or date.today()
    review_counts = review_counts or {}
    pl = calc.profit_and_loss(period_df)
    ea = calc.expense_analysis(period_df)
    monthly = calc.monthly_summary(period_df)
    changes, prev_month, last_month = trends.expense_category_changes(period_df)
    cf = calc.cash_flow(all_df, start, end, settings.get("opening_cash"))
    include_pending = bool(len(all_df) and (all_df["status"] == "Pending").any())

    def top_transactions(kind: str) -> List[Dict]:
        rows = period_df[period_df["transaction_type"] == kind].nlargest(5, "amount")
        return [{"date": str(r.date.date()), "description": str(r.description)[:80],
                 "amount": _f(r.amount)} for r in rows.itertuples()]

    def change_rows(frame: pd.DataFrame) -> List[Dict]:
        return [{"category": r.category, "previous_month": _f(r.previous), "latest_month": _f(r.latest),
                 "change": _f(r.change), "change_percent": _f(r.change_pct, 1)}
                for r in frame.itertuples()]

    ctx = {
        "currency": currency,
        "period": label,
        "data_used": "Confirmed + Pending (unreviewed)" if include_pending else "Confirmed transactions only",
        "profit_and_loss": {
            "total_revenue": _f(pl["total_revenue"]),
            "total_expenses": _f(pl["total_expenses"]),
            "net_profit": _f(pl["net_profit"]),
            "net_profit_margin_percent": _f(pl["net_margin"], 1),
            "revenue_by_category": {k: _f(v) for k, v in pl["revenue_by_category"].items()},
        },
        "expenses_by_category": [
            {"category": r.category, "amount": _f(r.total), "percent_of_expenses": _f(r.percent, 1)}
            for r in ea["by_category"].head(10).itertuples()],
        "monthly": [{"month": r.month, "revenue": _f(r.revenue), "expenses": _f(r.expenses),
                     "net_profit": _f(r.net_profit)} for r in monthly.itertuples()],
        "latest_month_may_be_incomplete": bool(len(monthly) and monthly.iloc[-1]["month"] == today.strftime("%Y-%m")),
        "expense_change_between_last_two_months": None if prev_month is None else {
            "previous_month": prev_month, "latest_month": last_month,
            "biggest_increases": change_rows(changes[changes["change"] > 0].head(3)),
            "biggest_decreases": change_rows(changes[changes["change"] < 0].tail(3)),
        },
        "cash_flow": {
            "opening_cash": _f(cf["opening_cash"]), "inflows": _f(cf["inflows"]),
            "outflows": _f(cf["outflows"]), "net_change": _f(cf["net_change"]),
            "closing_cash": _f(cf["closing_cash"]),
        },
        "largest_transactions": {"expenses": top_transactions("Expense"), "income": top_transactions("Income")},
    }

    notes = []
    pending = review_counts.get("pending_uncategorized", 0) + review_counts.get("pending_categorized", 0)
    if not include_pending and pending:
        notes.append(f"{pending} transactions are still Pending review and are NOT included in these numbers.")
    if review_counts.get("rejected"):
        notes.append(f"{review_counts['rejected']} transactions were rejected and are excluded.")
    if cf["opening_cash"] is None:
        notes.append("Opening cash was not entered, so closing cash is not available.")
    if cf["excluded_credit"]:
        notes.append(f"{cf['excluded_credit']} credit transactions are excluded from cash flow.")
    notes.append("Receivables, payables and anomaly detection are not available yet in this version.")
    notes.append("Figures are cash-basis; inventory purchases are counted as expenses when paid.")
    ctx["data_notes"] = notes
    return ctx


def context_to_json(ctx: Dict) -> str:
    return json.dumps(ctx, ensure_ascii=False)


# ---------------------------------------------------------------- 2. number checker
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|lakh|lac|crore|thousand|k)?\b", re.I)
_MULTIPLIER = {"million": 1e6, "lakh": 1e5, "lac": 1e5, "crore": 1e7, "thousand": 1e3, "k": 1e3}


def _collect_numbers(obj, found: List[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        found.append(float(obj))
    elif isinstance(obj, str):
        for token in re.findall(r"\d[\d,]*\.?\d*", obj):
            try:
                found.append(float(token.replace(",", "").rstrip(".")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_numbers(value, found)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _collect_numbers(value, found)


def verify_numbers(text: str, ctx: Dict) -> List[str]:
    """Return the figures in 'text' that do NOT appear in the verified data.
    This is a safety net, not a guarantee. Tiny numbers and years are ignored."""
    known: List[float] = []
    _collect_numbers(ctx, known)
    unmatched: List[str] = []
    for match in _NUMBER.finditer(text or ""):
        raw, suffix = match.group(1), (match.group(2) or "").lower()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        tolerance = 0.005
        if suffix:
            value *= _MULTIPLIER[suffix]
            tolerance = 0.05                      # "4.2 million" is rounded
        elif value < 10 or (2000 <= value <= 2100 and "," not in raw):
            continue
        if not any(abs(value - k) <= max(0.51, tolerance * abs(k)) for k in known):
            label = raw + (f" {suffix}" if suffix else "")
            if label not in unmatched:
                unmatched.append(label)
    return unmatched


# ---------------------------------------------------------------- 3. insights
def _validate_insights(data) -> Optional[Dict]:
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        return None

    def clean_list(value) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip()[:400] for v in value if isinstance(v, str) and v.strip()][:4]

    return {"summary": data["summary"].strip()[:1200],
            "concerns": clean_list(data.get("concerns")),
            "recommendations": clean_list(data.get("recommendations"))}


def generate_insights(ctx: Dict, ask: Optional[Callable] = None) -> Dict:
    """Ask the AI for a summary, concerns and recommendations. Raises AIError if unreachable."""
    ask = ask or groq_client.chat_completion
    messages = [
        {"role": "system", "content": ANALYST_SYSTEM},
        {"role": "user", "content": "VERIFIED DATA (JSON):\n" + context_to_json(ctx)
                                    + "\n\nWrite the analysis now. JSON only."},
    ]
    text = ask(messages, json_mode=True, max_tokens=2500, temperature=0.2)
    result = _validate_insights(groq_client.parse_json_reply(text))
    if result is None:     # malformed reply: show the raw text instead of crashing
        result = {"summary": text.strip()[:1500], "concerns": [], "recommendations": [], "raw": True}
    all_text = " ".join([result["summary"]] + result["concerns"] + result["recommendations"])
    result["unverified_numbers"] = verify_numbers(all_text, ctx)
    return result


# ---------------------------------------------------------------- 4. chat
def answer_question(question: str, ctx: Dict, history: List[Dict],
                    ask: Optional[Callable] = None) -> str:
    """Question -> verified data block -> AI explanation."""
    ask = ask or groq_client.chat_completion
    messages = [{"role": "system",
                 "content": CHAT_SYSTEM + "\n\nVERIFIED BUSINESS DATA (JSON):\n" + context_to_json(ctx)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    messages.append({"role": "user", "content": question.strip()[:1000]})
    return ask(messages, json_mode=False, max_tokens=1500, temperature=0.2)
