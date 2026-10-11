"""Financial Reports page: Profit & Loss and ratios."""
import streamlit as st

from accounting import calculations as calc
from accounting import ratios
from database import crud
from ui import common


def render() -> None:
    st.title("📑 Financial Reports")
    st.caption("Every number on this page is calculated by Python, not by AI.")
    data = common.report_controls()
    if data is None:
        return
    if data.period_data.empty:
        st.info("No transactions in the selected period.")
        return

    currency = st.session_state.profile["currency"]
    pl = calc.profit_and_loss(data.period_data)
    tab_pl, tab_ratios = st.tabs(["Profit & Loss", "Financial Ratios"])

    with tab_pl:
        for note in calc.data_quality_notes(data.period_data):
            st.warning(note)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Revenue", common.money(pl["total_revenue"], currency))
        k2.metric("Expenses", common.money(pl["total_expenses"], currency))
        k3.metric("Net Profit", common.money(pl["net_profit"], currency))
        k4.metric("Profit Margin", "n/a" if pl["net_margin"] is None else f"{pl['net_margin']:.1f}%")

        statement = calc.format_pl_text(pl, currency, data.label)
        st.code(statement, language=None)
        st.download_button("⬇️ Download statement (text)", statement, "profit_and_loss.txt")
        st.caption("MVP note: figures are cash-basis. Inventory purchases are counted as expenses "
                   "when paid, and unsold stock is not shown as an asset.")

    with tab_ratios:
        try:
            settings = crud.get_numeric_settings()
        except Exception:
            settings = {}
        for ratio in ratios.compute_all_ratios(pl, settings, currency):
            with st.container(border=True):
                st.markdown(f"**{ratio['name']}**")
                if ratio["available"]:
                    shown = f"{ratio['value']:.1f}%" if ratio["unit"] == "%" else f"{ratio['value']:.2f}x"
                    st.metric("Value", shown)
                    st.write(ratio["meaning"])
                else:
                    st.info(ratio["missing"])
                st.caption(f"Formula: {ratio['formula']}")
