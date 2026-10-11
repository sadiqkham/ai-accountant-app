"""Transactions page: add one transaction, view all, load sample data."""
from datetime import date

import pandas as pd
import streamlit as st

from database import db
from utils import file_processing as fp
from utils.helpers import ALL_CATEGORIES, PAYMENT_METHODS, TRANSACTION_TYPES
from utils.sample_data import generate_sample_dataframe

NO_CATEGORY = "(let AI suggest later)"


def _add_form() -> None:
    st.subheader("Add a transaction")
    with st.form("manual_entry", clear_on_submit=True):
        c1, c2 = st.columns(2)
        tx_date = c1.date_input("Date", value=date.today(), format="DD/MM/YYYY")
        amount = c2.number_input("Amount", min_value=0.0, step=100.0, format="%.2f")
        description = st.text_input("Description", placeholder="e.g. Paid electricity bill")
        c3, c4, c5 = st.columns(3)
        tx_type = c3.selectbox("Type", TRANSACTION_TYPES, index=1)
        method = c4.selectbox("Payment method", PAYMENT_METHODS)
        party = c5.text_input("Customer / vendor")
        category = st.selectbox("Category (optional)", [NO_CATEGORY] + ALL_CATEGORIES)
        allow_dup = st.checkbox("Save even if it looks like a duplicate")
        submitted = st.form_submit_button("Add transaction")

    if not submitted:
        return

    row = pd.DataFrame([{
        "Date": tx_date.strftime("%d-%m-%Y"), "Description": description,
        "Amount": amount, "Type": tx_type, "Payment_Method": method, "Party": party,
        "Category": "" if category == NO_CATEGORY else category,
    }])
    result = fp.clean_transactions(row)
    if not result.issues.empty:
        st.error("Cannot save: " + "; ".join(result.issues["Problem"]))
        return
    checked = fp.mark_duplicates(result.valid, db.get_existing_keys())
    if checked["Duplicate_Reason"].iloc[0] and not allow_dup:
        st.warning("This looks like a duplicate of a saved transaction. "
                   "Tick the box to save it anyway.")
        return
    try:
        db.insert_transactions(result.valid)
        st.success("Transaction saved (status: Pending).")
    except db.DatabaseError as exc:
        st.error(str(exc))


def _view_all() -> None:
    st.subheader("All transactions")
    try:
        data = db.get_transactions()
    except db.DatabaseError as exc:
        st.error(str(exc))
        return

    if data.empty:
        st.info("No transactions yet. Add one, upload a file, or load the sample data.")
        if st.button("📥 Load sample data (about 115 transactions)"):
            sample = fp.clean_transactions(generate_sample_dataframe())
            # Saved including the planted duplicates, so we can test anomaly detection later
            db.insert_transactions(sample.valid)
            st.rerun()
        return

    f1, f2 = st.columns(2)
    types = f1.multiselect("Filter by type", sorted(data["transaction_type"].dropna().unique()))
    statuses = f2.multiselect("Filter by status", sorted(data["status"].dropna().unique()))
    shown = data
    if types:
        shown = shown[shown["transaction_type"].isin(types)]
    if statuses:
        shown = shown[shown["status"].isin(statuses)]

    m1, m2, m3 = st.columns(3)
    m1.metric("Total saved", len(data))
    m2.metric("Pending review", int((data["status"] == "Pending").sum()))
    m3.metric("Shown now", len(shown))

    st.dataframe(shown, column_config={
        "amount": st.column_config.NumberColumn("Amount", format="%.0f")})
    st.download_button("⬇️ Download as CSV (backup)", data.to_csv(index=False),
                       "transactions_backup.csv", "text/csv")

    with st.expander("⚠️ Danger zone"):
        confirm = st.checkbox("I understand this deletes ALL saved transactions")
        if st.button("Delete all transactions", disabled=not confirm):
            db.delete_all_transactions()
            st.rerun()


def render() -> None:
    st.title("🧾 Transactions")
    tab_add, tab_view = st.tabs(["➕ Add transaction", "📋 All transactions"])
    with tab_add:
        _add_form()
    with tab_view:
        _view_all()
