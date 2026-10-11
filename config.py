"""Central settings for the AI Accountant app."""
import os

APP_NAME = "AI Accountant / SME Financial Assistant"
DEFAULT_CURRENCY = "PKR"

# Models are tried in order. If the first is unavailable, the next is used.
# You can override the first choice without editing code: os.environ["GROQ_MODEL"] = "..."
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODELS = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
GROQ_TIMEOUT_SECONDS = 30

DISCLAIMER = (
    "This application provides accounting and financial insights based on "
    "user-provided data. It is not a substitute for a qualified accountant, "
    "auditor, tax adviser, or legal professional. Users should verify important "
    "financial decisions and statutory requirements independently."
)

MISSING_KEY_MESSAGE = (
    "GROQ_API_KEY is not configured.\n"
    "Please add it to your environment/secrets."
)


def get_groq_api_key():
    """Return the Groq key from env vars or Streamlit secrets, or None.
    The key is never printed or logged."""
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("GROQ_API_KEY")  # used on Streamlit Cloud later
    except Exception:
        return None
