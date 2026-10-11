"""Anomaly Detection page."""
import streamlit as st

from accounting import anomaly_detection as anomaly
from ai import explainer, groq_client
from config import MISSING_KEY_MESSAGE
from database import review_db
from ui import common

ICON = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}
MAX_CARDS = 15


def _flag_card(row, currency: str) -> None:
    with st.container(border=True):
        st.markdown(f"**⚠️ REVIEW NEEDED** · {ICON[row.risk_level]} Risk level: **{row.risk_level}**")
        st.markdown(f"**{row.description}** · {currency} {row.amount:,.0f} · {row.date:%d %b %Y} · "
                    f"{row.category} · transaction #{row.id}")
        for reason in str(row.reason).split(" • "):
            st.write("•", reason)
        st.caption("Important: this does NOT mean the transaction is fraudulent. "
                   "It only means it should be reviewed.")


def _duplicates_section(flags) -> None:
    dup_ids = flags[flags["rules"].str.contains("Possible duplicate", na=False)]["id"].tolist()
    if not dup_ids:
        return
    with st.expander(f"Handle {len(dup_ids)} possible duplicate(s)"):
        st.write("Each flagged copy matches an earlier transaction exactly. If they really are duplicates, "
                 "reject the copies so they are left out of your reports. You can undo this later in "
                 "**Review & Categorize → Rejected → Reclassify**.")
        confirm = st.checkbox("I checked them and want to reject these copies")
        if st.button(f"Reject {len(dup_ids)} flagged duplicate(s)", disabled=not confirm):
            n = review_db.set_status(dup_ids, "Rejected")
            st.success(f"Rejected {n} transaction(s).")
            st.rerun()


def _ai_section(shown, flags, currency: str) -> None:
    st.subheader("🤖 AI explanation (optional)")
    st.caption("The AI explains the findings in plain language. It does not decide what is unusual.")
    if st.button("Explain the top flagged items", disabled=shown.empty):
        try:
            with st.spinner("Asking Groq..."):
                st.session_state.anomaly_ai = explainer.explain_flags(shown, currency)
        except groq_client.GroqConfigError:
            st.error(MISSING_KEY_MESSAGE)
        except groq_client.AIError as exc:
            st.error(str(exc))
    saved = st.session_state.get("anomaly_ai")
    if not saved:
        return
    names = dict(zip(flags["id"], flags["description"]))
    for tx_id, item in saved["items"].items():
        st.markdown(f"**#{tx_id} {names.get(tx_id, '')}**")
        st.write(item["explanation"])
        if item["what_to_check"]:
            st.caption("What to check: " + item["what_to_check"])
    if not saved["items"] and saved.get("raw"):
        st.warning("The AI reply was not in the expected format:")
        st.text(saved["raw"])
    if saved["unverified_numbers"]:
        st.warning("⚠️ These figures could not be matched to the calculated findings: "
                   + ", ".join(saved["unverified_numbers"]))
    st.caption("AI-generated explanation. Not professional advice.")


def render() -> None:
    st.title("🔍 Anomaly Detection")
    st.info("These automatic checks find transactions that deserve a HUMAN REVIEW. A flag does NOT mean "
            "fraud or a mistake. Tip: switch 'Data used' to the preview to also check Pending transactions.")
    data = common.report_controls()
    if data is None:
        return
    currency = st.session_state.profile["currency"]

    result = anomaly.detect_anomalies(data.all_data, currency)
    if result.message:
        st.warning(result.message)
    flags = anomaly.filter_flags_by_period(result.flags, data.start, data.end)
    alerts = anomaly.filter_alerts_by_period(result.category_alerts, data.start, data.end)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Transactions checked", result.analysed)
    m2.metric("🔴 High", int((flags["risk_level"] == "High").sum()))
    m3.metric("🟠 Medium", int((flags["risk_level"] == "Medium").sum()))
    m4.metric("🟡 Low", int((flags["risk_level"] == "Low").sum()))

    if flags.empty:
        st.success("No unusual transactions found in this period.")
    else:
        levels = st.multiselect("Show risk levels", ["High", "Medium", "Low"], default=["High", "Medium"])
        shown = flags[flags["risk_level"].isin(levels)]
        st.caption(f"Showing the top {min(len(shown), MAX_CARDS)} of {len(shown)}.")
        for row in shown.head(MAX_CARDS).itertuples():
            _flag_card(row, currency)

        with st.expander("All flagged transactions (table)"):
            table = flags[["id", "date", "description", "amount", "category", "party",
                           "risk_level", "rules", "reason"]].copy()
            table["date"] = table["date"].dt.strftime("%d-%m-%Y")
            st.dataframe(table, column_config={"amount": st.column_config.NumberColumn(format="%.0f")})

        _duplicates_section(flags)
        _ai_section(shown, flags, currency)

    st.subheader("Category spending spikes")
    if alerts.empty:
        st.caption("No sudden month-to-month jumps in any expense category.")
    else:
        st.dataframe(alerts, column_config={
            "amount": st.column_config.NumberColumn(format="%.0f"),
            "typical_before": st.column_config.NumberColumn("Recent average", format="%.0f"),
            "change_pct": st.column_config.NumberColumn("Change %", format="%.0f")})
        st.caption("A month still in progress can look smaller than it will finally be.")
