"""Settings: business profile, opening balances, system status and backup."""
import math
import os
from datetime import date

import streamlit as st

from accounting import calculations as calc
from accounting import ledger_calc
from ai.groq_client import test_connection
from config import GROQ_MODEL
from database import crud, db, profile_db
from database import ledger as ledger_db
from utils.file_processing import _to_number

BUSINESS_TYPES = ["Retail", "Restaurant", "Freelancer", "Service", "Startup", "Other"]
FIELDS = [
    ("opening_cash", "Opening cash + bank balance",
     "Money you had BEFORE your first recorded transaction. Used for Cash Flow.", True),
    ("current_assets", "Current assets",
     "Cash, bank, money customers owe you, and stock value. Used for the Current Ratio.", False),
    ("current_liabilities", "Current liabilities",
     "Bills and loans due within 12 months. Used for the Current Ratio.", False),
]


def _profile_tab() -> None:
    p = st.session_state.profile
    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Business name", p["name"])
        index = BUSINESS_TYPES.index(p["type"]) if p["type"] in BUSINESS_TYPES else 0
        btype = c2.selectbox("Business type", BUSINESS_TYPES, index=index)
        industry = c1.text_input("Industry", p["industry"])
        city = c2.text_input("City", p["city"])
        currency = c1.text_input("Currency", p["currency"])
        saved = st.form_submit_button("Save profile")
    if saved:
        if not name.strip() or not currency.strip():
            st.error("Business name and currency cannot be empty.")
            return
        profile = {"name": name.strip(), "type": btype, "industry": industry.strip(),
                   "city": city.strip(), "currency": currency.strip().upper()}
        try:
            profile_db.save_profile(profile)
        except db.DatabaseError as exc:
            st.error(str(exc))
            return
        st.session_state.profile = profile
        st.success("Profile saved.")


def _suggestions(currency: str) -> None:
    """Show numbers calculated from your own data to help you fill in the fields."""
    try:
        opening = crud.get_numeric_settings().get("opening_cash")
        prepared = calc.prepare(db.get_transactions(), include_pending=False)
        cash = calc.cash_flow(prepared, None, None, opening)["closing_cash"]
        today = date.today()
        rec = ledger_calc.summarize(ledger_calc.prepare_ledger(ledger_db.list_entries("receivable"), today))
        pay = ledger_calc.summarize(ledger_calc.prepare_ledger(ledger_db.list_entries("payable"), today))
    except Exception:
        return
    lines = []
    if cash is None:
        lines.append("Enter opening cash first, then the app can calculate your current cash.")
    else:
        lines.append(f"Calculated cash now: {currency} {cash:,.0f}  +  receivables: {currency} {rec['total_due']:,.0f}"
                     f"  =  {currency} {cash + rec['total_due']:,.0f}. Add your stock value and any other current assets yourself.")
    lines.append(f"Payables: {currency} {pay['total_due']:,.0f}. Add loans or other bills due within 12 months yourself.")
    st.info("💡 Suggestions from your data (the app will not guess missing items):\n\n" + "\n\n".join(lines))


def _balances_tab() -> None:
    st.caption("Leave a field empty if you don't know it. The app then says 'insufficient data' instead of guessing.")
    currency = st.session_state.profile["currency"]
    _suggestions(currency)
    current = crud.get_numeric_settings()
    with st.form("settings_form"):
        entered = {}
        for key, label, help_text, _ in FIELDS:
            saved = current.get(key)
            entered[key] = st.text_input(f"{label} ({currency})", value="" if saved is None else f"{saved:.0f}",
                                         help=help_text)
        submitted = st.form_submit_button("Save balances")
    if not submitted:
        return
    parsed, errors = {}, []
    for key, label, _, allow_negative in FIELDS:
        text = entered[key].strip()
        if text == "":
            parsed[key] = None
            continue
        number = _to_number(text)
        if isinstance(number, float) and math.isnan(number):
            errors.append(f"{label}: '{text}' is not a valid number.")
        elif number < 0 and not allow_negative:
            errors.append(f"{label} cannot be negative.")
        else:
            parsed[key] = number
    if errors:
        for message in errors:
            st.error(message)
        return
    for key, value in parsed.items():
        crud.set_numeric_setting(key, value)
    st.success("Balances saved.")


def _system_tab() -> None:
    c1, c2 = st.columns(2)
    c1.metric("Saved transactions", db.count_transactions())
    c2.caption(f"Database file: {db.DB_PATH}")
    st.caption(f"AI model: {GROQ_MODEL}")
    if st.button("Test Groq connection"):
        with st.spinner("Contacting Groq..."):
            ok, message = test_connection()
        (st.success if ok else st.error)(message)

    st.subheader("Backup")
    st.caption("Colab files disappear when the runtime resets. Download a backup now and then.")
    if os.path.exists(db.DB_PATH):
        with open(db.DB_PATH, "rb") as handle:
            st.download_button("⬇️ Download database backup", handle.read(), "accountant_backup.db")


def render() -> None:
    st.title("⚙️ Settings")
    tab_profile, tab_balances, tab_system = st.tabs(["🏢 Business profile", "💼 Opening balances", "🖥️ System"])
    with tab_profile:
        _profile_tab()
    with tab_balances:
        _balances_tab()
    with tab_system:
        _system_tab()
