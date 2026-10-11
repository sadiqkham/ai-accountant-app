"""A very simple shared-password gate (MVP).
If APP_PASSWORD is set (environment variable or Streamlit secret), the app asks for it.
If it is NOT set (for example in Colab), the app opens normally.
This is NOT a replacement for real user accounts."""
import hmac
import os
from typing import Optional

import streamlit as st


def configured_password() -> Optional[str]:
    password = os.getenv("APP_PASSWORD")
    if password:
        return password
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


def check_password(entered: Optional[str], expected: Optional[str]) -> bool:
    """Compare in a way that does not leak information through timing."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(str(entered).encode("utf-8"), str(expected).encode("utf-8"))


def require_password() -> None:
    """Call at the top of app.py. Stops the page until the right password is entered."""
    expected = configured_password()
    if not expected or st.session_state.get("authenticated"):
        return
    st.title("🔒 AI Accountant")
    with st.form("login_form"):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if check_password(entered, expected):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()
