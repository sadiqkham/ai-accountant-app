# AI Accountant / SME Financial Assistant

A beginner-friendly financial assistant for small businesses, built with Python, Streamlit and the Groq API.

**Key idea:** Python does ALL the accounting maths (totals, profit, ratios, cash flow, anomaly checks).
The AI only classifies descriptions and explains numbers that Python already calculated.

## Features
- Manual entry and CSV/Excel upload with validation (dates, amounts, duplicates, flexible column names)
- AI transaction categorization (strict JSON, validated against a fixed category list)
- Human review: accept, edit, reject, reclassify. Only confirmed transactions feed reports
- Profit and Loss, expense analysis, financial ratios, cash flow
- Receivables and payables with aging
- Anomaly detection (statistics and rules) with plain-language reasons
- AI chat and insights based only on verified numbers
- Dashboard with KPI cards, charts and alerts

## Safety rules
- The AI never calculates totals and never invents numbers (a checker flags figures it cannot match).
- Unusual transactions are flagged for REVIEW. They are never called fraud.
- Disclaimer: this application provides accounting and financial insights based on user-provided data.
  It is not a substitute for a qualified accountant, auditor, tax adviser, or legal professional.

## Run locally
1. Install Python 3.11 or newer.
2. Create a virtual environment and install packages:

        python -m venv .venv
        source .venv/bin/activate        (Windows: .venv\Scripts\activate)
        pip install -r requirements.txt

3. Create the file .streamlit/secrets.toml (never commit it) with:

        GROQ_API_KEY = "paste-your-key-here"
        APP_PASSWORD = "choose-a-password"     (optional)

4. Start the app:

        streamlit run app.py

## Deploy on Streamlit Community Cloud
1. Push this folder to a PRIVATE GitHub repository (the .gitignore keeps secrets and databases out).
2. At share.streamlit.io choose "New app", select the repository, branch main, main file app.py.
3. Open "Advanced settings" and paste your secrets (GROQ_API_KEY, and APP_PASSWORD to lock the app).
4. Deploy.

Important: on Streamlit Cloud the SQLite file is temporary. It is reset when the app restarts or is redeployed.
Download a backup from Settings, System regularly. Anyone who knows the password shares the same data,
so use demo data unless you have added real user accounts.

## Project structure
    app.py                 entry point and navigation
    config.py              settings and disclaimer
    accounting/            calculations, reports, ratios, anomaly detection (no AI)
    ai/                    Groq client, categorizer, insights, prompts, anomaly explainer
    database/              SQLite storage, review actions, ledger, profile
    ui/                    Streamlit pages
    utils/                 file processing, helpers, sample data, simple auth
    data/                  sample_transactions.csv (synthetic, in PKR)
    tests/test_all.py      all automated tests

## Tests
    python tests/test_all.py            (offline tests, no API key needed)
    python tests/test_all.py --live     (also makes a few real Groq calls)

## Known limitations (MVP)
- Cash-basis accounting: inventory purchases are counted as expenses when paid.
- Receivables and payables are a separate ledger, not linked to the transaction list.
- Single business, no user accounts, simple shared password only.
- SQLite is not suitable for permanent hosting on Streamlit Cloud (use a hosted database for that).
- Not designed for tax filing or statutory reporting.
