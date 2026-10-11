"""Dashboard: KPIs, charts, alerts, flagged transactions and an AI summary."""
from datetime import date

import plotly.express as px
import streamlit as st

from accounting import alerts as alert_logic
from accounting import anomaly_detection as anomaly
from accounting import calculations as calc
from accounting import ledger_calc
from ai import groq_client, insights
from config import DISCLAIMER, MISSING_KEY_MESSAGE
from database import crud, review_db
from database import ledger as ledger_db
from ui import common, context_helper

ICON = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}
MEASURE_NAMES = {"revenue": "Revenue", "expenses": "Expenses", "net_profit": "Net profit"}


def _ai_summary(data, currency: str) -> None:
    st.subheader("🤖 AI financial summary")
    st.caption("The AI explains the calculated numbers above. It does not calculate them.")
    if st.button("Generate AI summary"):
        try:
            with st.spinner("Asking Groq..."):
                ctx = context_helper.build_full_context(data, currency)
                result = insights.generate_insights(ctx)
            st.session_state.ai_insights = {"result": result, "period": ctx["period"]}
        except groq_client.GroqConfigError:
            st.error(MISSING_KEY_MESSAGE)
        except groq_client.AIError as exc:
            st.error(str(exc))
    saved = st.session_state.get("ai_insights")
    if not saved:
        return
    if saved["period"] != data.label:
        st.info(f"This summary was generated for: {saved['period']}. Click the button to refresh.")
    result = saved["result"]
    st.write(result["summary"])
    for title, items in (("Main concerns", result["concerns"]), ("Recommendations", result["recommendations"])):
        if items:
            st.markdown(f"**{title}**")
            for item in items:
                st.write("•", item)
    if result.get("unverified_numbers"):
        st.warning("⚠️ These figures could not be matched to the calculated data: "
                   + ", ".join(result["unverified_numbers"]) + ". Please verify them.")
    st.caption("AI-generated explanation. Not professional advice.")


def render() -> None:
    st.title("📊 Dashboard")
    data = common.report_controls()
    if data is None:
        return
    if data.period_data.empty:
        st.info("No transactions in the selected period.")
        return

    currency = st.session_state.profile["currency"]
    today = date.today()
    period = data.period_data
    pl = calc.profit_and_loss(period)
    monthly = calc.monthly_summary(period)
    expense_view = calc.expense_analysis(period)

    try:
        settings = crud.get_numeric_settings()
        counts = review_db.counts()
    except Exception:
        settings, counts = {}, {}
    cash = calc.cash_flow(data.all_data, data.start, data.end, settings.get("opening_cash"))
    receivables = ledger_calc.summarize(ledger_calc.prepare_ledger(ledger_db.list_entries("receivable"), today))
    payables = ledger_calc.summarize(ledger_calc.prepare_ledger(ledger_db.list_entries("payable"), today))
    result = anomaly.detect_anomalies(data.all_data, currency)
    flags = anomaly.filter_flags_by_period(result.flags, data.start, data.end)

    # Change versus the previous completed month
    deltas = {}
    months = alert_logic.comparison_months(monthly, today)
    if months:
        previous, latest = months
        rows = monthly.set_index("month")
        for key in ("revenue", "expenses", "net_profit"):
            change = alert_logic.pct_change(rows.at[latest, key], rows.at[previous, key])
            deltas[key] = None if change is None else f"{change:+.1f}%"

    # ---- KPI cards ----
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Revenue", common.money(pl["total_revenue"], currency), delta=deltas.get("revenue"))
    k2.metric("Expenses", common.money(pl["total_expenses"], currency), delta=deltas.get("expenses"),
              delta_color="inverse")
    k3.metric("Net Profit", common.money(pl["net_profit"], currency), delta=deltas.get("net_profit"))
    k4.metric("Cash Balance", "n/a" if cash["closing_cash"] is None else common.money(cash["closing_cash"], currency),
              help="Needs opening cash in Settings." if cash["closing_cash"] is None else None)
    k5, k6, k7 = st.columns(3)
    k5.metric("Profit Margin", "n/a" if pl["net_margin"] is None else f"{pl['net_margin']:.1f}%")
    k6.metric("Receivables", common.money(receivables["total_due"], currency))
    k7.metric("Payables", common.money(payables["total_due"], currency))
    if months:
        st.caption(f"Changes compare {months[1]} with {months[0]} (completed months). "
                   "Receivables and payables are as of today.")

    # ---- Alerts ----
    include_pending = bool((data.all_data["status"] == "Pending").any())
    alerts = alert_logic.build_alerts(pl, monthly, flags, receivables, payables, counts,
                                      {"closing": cash["closing_cash"]}, today, currency, include_pending)
    st.subheader("🔔 Alerts")
    if not alerts:
        st.success("No alerts. Nothing needs attention based on the recorded data.")
    for alert in alerts[:8]:
        getattr(st, alert["level"])(alert["text"])

    # ---- Charts ----
    c1, c2 = st.columns([3, 2])
    trend = monthly.melt(id_vars="month", value_vars=list(MEASURE_NAMES), var_name="Measure", value_name="Amount")
    trend["Measure"] = trend["Measure"].map(MEASURE_NAMES)
    c1.plotly_chart(px.line(trend, x="month", y="Amount", color="Measure", markers=True,
                            title="Revenue, expense and profit trend"))
    if not expense_view["by_category"].empty:
        c2.plotly_chart(px.pie(expense_view["by_category"], names="category", values="total", hole=0.45,
                               title="Expense breakdown"))
    st.caption("The latest month may be incomplete if it is still in progress.")

    # ---- Flagged transactions ----
    st.subheader("🔍 Transactions to review")
    top = flags[flags["risk_level"].isin(["High", "Medium"])].head(3)
    if top.empty:
        st.caption("No high or medium risk transactions in this period.")
    for row in top.itertuples():
        first_reason = str(row.reason).split(" • ")[0]
        st.write(f"{ICON[row.risk_level]} **{row.description}**, {currency} {row.amount:,.0f} "
                 f"({row.date:%d %b %Y}): {first_reason}")
    if not top.empty:
        st.caption("Open **Anomaly Detection** for details. A flag means 'review', not 'fraud'.")

    _ai_summary(data, currency)
    st.divider()
    st.caption(DISCLAIMER)
