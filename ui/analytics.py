"""Expenses and Cash Flow pages (with Plotly charts)."""
import plotly.express as px
import streamlit as st

from accounting import calculations as calc
from database import crud
from ui import common


def render_expenses() -> None:
    st.title("💸 Expense Analysis")
    st.caption("Every number on this page is calculated by Python, not by AI.")
    data = common.report_controls()
    if data is None:
        return
    currency = st.session_state.profile["currency"]
    analysis = calc.expense_analysis(data.period_data)
    by_category = analysis["by_category"]
    if by_category.empty:
        st.info("No expenses in the selected period.")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Total expenses", common.money(analysis["total"], currency))
    m2.metric("Biggest category", by_category.iloc[0]["category"])
    m3.metric("Share of biggest", f"{by_category.iloc[0]['percent']:.1f}%")

    c1, c2 = st.columns(2)
    bar = px.bar(by_category, x="category", y="total", title="Expenses by category",
                 labels={"category": "Category", "total": f"Amount ({currency})"})
    c1.plotly_chart(bar)
    donut = px.pie(by_category, names="category", values="total", hole=0.45,
                   title="Share of total expenses")
    c2.plotly_chart(donut)

    monthly = analysis["monthly"]
    trend = px.line(monthly, x="month", y="total", markers=True, title="Monthly expense trend",
                    labels={"month": "Month", "total": f"Amount ({currency})"})
    st.plotly_chart(trend)
    st.caption("The latest month may be incomplete, so it can look lower than earlier months.")

    st.subheader("Category table")
    table = by_category.rename(columns={"category": "Category", "total": "Total",
                                        "transactions": "Transactions", "percent": "% of expenses"})
    st.dataframe(table, column_config={
        "Total": st.column_config.NumberColumn(format="%.0f"),
        "% of expenses": st.column_config.NumberColumn(format="%.1f")})


def render_cash_flow() -> None:
    st.title("🏦 Cash Flow")
    st.caption("Every number on this page is calculated by Python, not by AI.")
    data = common.report_controls()
    if data is None:
        return
    currency = st.session_state.profile["currency"]
    try:
        opening_base = crud.get_numeric_settings().get("opening_cash")
    except Exception:
        opening_base = None

    cf = calc.cash_flow(data.all_data, data.start, data.end, opening_base)

    if cf["opening_cash"] is None:
        st.warning("Opening cash is not set (see **Settings**), so closing cash cannot be shown. "
                   "Only the net cash movement is calculated.")
        summary = [f"{'+ Cash Inflows':<22}{currency} {cf['inflows']:>13,.0f}",
                   f"{'- Cash Outflows':<22}{currency} {cf['outflows']:>13,.0f}",
                   "-" * 40,
                   f"{'Net Cash Movement':<22}{currency} {cf['net_change']:>13,.0f}"]
    else:
        summary = [f"{'Opening Cash':<22}{currency} {cf['opening_cash']:>13,.0f}",
                   f"{'+ Cash Inflows':<22}{currency} {cf['inflows']:>13,.0f}",
                   f"{'- Cash Outflows':<22}{currency} {cf['outflows']:>13,.0f}",
                   "-" * 40,
                   f"{'Closing Cash':<22}{currency} {cf['closing_cash']:>13,.0f}"]
    st.code("\n".join(summary), language=None)

    if cf["excluded_credit"]:
        st.caption(f"{cf['excluded_credit']} transaction(s) paid on 'Credit' are excluded (no cash moved yet).")
    if cf["excluded_balance_sheet"]:
        st.caption(f"{cf['excluded_balance_sheet']} Asset/Liability transaction(s) are excluded "
                   "because their cash direction is not known.")

    monthly = cf["monthly"]
    if not monthly.empty:
        chart = px.bar(monthly, x="month", y=["inflow", "outflow"], barmode="group",
                       title="Monthly cash inflows and outflows",
                       labels={"value": f"Amount ({currency})", "month": "Month", "variable": ""})
        st.plotly_chart(chart)
        st.subheader("By month")
        st.dataframe(monthly)
        st.subheader("By payment method")
        st.dataframe(cf["by_method"])
