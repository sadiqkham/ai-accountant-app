"""AI Accountant / SME Financial Assistant: main entry point."""
import logging
import streamlit as st

from config import DEFAULT_CURRENCY, DISCLAIMER
from database import db, profile_db
from database import ledger as ledger_db
from ui import (analytics, anomalies, chat, dashboard, ledger_page, reports, review,
                settings, transactions, upload)
from utils import auth

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="AI Accountant", page_icon="📊", layout="wide")

# ---- Ask for the password first (only if APP_PASSWORD is configured) ----
auth.require_password()

# ---- Create tables, add new columns, load the saved business profile ----
try:
    db.init_db()
    ledger_db.ensure_columns()
except db.DatabaseError as exc:
    st.error(f"Could not open the database: {exc}")
    st.stop()

if "profile" not in st.session_state:
    try:
        st.session_state.profile = profile_db.get_profile()
    except db.DatabaseError:
        st.session_state.profile = dict(profile_db.DEFAULT_PROFILE, currency=DEFAULT_CURRENCY)

PAGES = ["Dashboard", "Transactions", "Upload Data", "Review & Categorize",
         "Financial Reports", "Expenses", "Cash Flow", "Receivables", "Payables",
         "Anomaly Detection", "AI Financial Assistant", "Settings"]

# ---- Sidebar ----
st.sidebar.title("📊 AI ACCOUNTANT")
page = st.sidebar.radio("Navigation", PAGES)
st.sidebar.caption(f"Business: {st.session_state.profile['name']}")
with st.sidebar.expander("⚠️ Disclaimer"):
    st.caption(DISCLAIMER)

# ---- Pages ----
ROUTES = {
    "Dashboard": dashboard.render,
    "Transactions": transactions.render,
    "Upload Data": upload.render,
    "Review & Categorize": review.render,
    "Financial Reports": reports.render,
    "Expenses": analytics.render_expenses,
    "Cash Flow": analytics.render_cash_flow,
    "Receivables": lambda: ledger_page.render("receivable"),
    "Payables": lambda: ledger_page.render("payable"),
    "Anomaly Detection": anomalies.render,
    "AI Financial Assistant": chat.render,
    "Settings": settings.render,
}
try:
    ROUTES[page]()
except Exception:                      # one broken page must not show an ugly crash
    logging.getLogger(__name__).exception("Page failed: %s", page)
    st.error("Something went wrong on this page. Your data is safe. "
             "Try reloading, and share the error text from the log if it keeps happening.")
