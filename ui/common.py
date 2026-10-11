"""Controls shared by the report pages."""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from accounting import calculations as calc
from database import db

CONFIRMED_ONLY = "Confirmed only (official)"
PREVIEW = "Confirmed + Pending (preview, not reviewed)"


@dataclass
class ReportData:
    all_data: pd.DataFrame      # every usable transaction (needed for opening cash)
    period_data: pd.DataFrame   # only the chosen period
    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]
    label: str


def money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.0f}"


def report_controls() -> Optional[ReportData]:
    """Show the Period and Data selectors, load data, and return it (or None)."""
    c1, c2 = st.columns(2)
    period = c1.selectbox("Period", calc.PERIODS, key="rep_period")
    source = c2.selectbox("Data used", [CONFIRMED_ONLY, PREVIEW], key="rep_source")
    include_pending = source == PREVIEW

    custom_start = custom_end = None
    if period == "Custom range":
        d1, d2 = st.columns(2)
        custom_start = d1.date_input("From", value=date.today().replace(day=1),
                                     format="DD/MM/YYYY", key="rep_from")
        custom_end = d2.date_input("To", value=date.today(), format="DD/MM/YYYY", key="rep_to")
        if custom_start > custom_end:
            st.error("'From' date must be before 'To' date.")
            return None

    try:
        raw = db.get_transactions()
    except db.DatabaseError as exc:
        st.error(str(exc))
        return None
    if raw.empty:
        st.info("No transactions yet. Go to **Transactions** to add or load data.")
        return None

    df = calc.prepare(raw, include_pending)
    if df.empty:
        st.warning("There are no **Confirmed** transactions yet. Go to **Transactions**, scroll to "
                   "**Quick categorize**, apply the rules and confirm. Or switch 'Data used' to the preview.")
        return None
    if include_pending:
        st.warning("Preview mode: this includes Pending transactions that have NOT been reviewed.")

    start, end = calc.get_period_dates(period, date.today(), custom_start, custom_end)
    period_df = calc.filter_by_date(df, start, end)
    return ReportData(df, period_df, start, end, calc.describe_period(start, end))
