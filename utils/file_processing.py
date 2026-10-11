"""Read CSV/Excel files, match column names, validate and clean the data."""
import io
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

import numpy as np
import pandas as pd

from utils.helpers import transaction_key

logger = logging.getLogger(__name__)

MAX_FILE_MB = 10
REQUIRED_COLUMNS = ["Date", "Description", "Amount"]
OPTIONAL_COLUMNS = ["Type", "Payment_Method", "Party", "Category"]

# Different names that mean the same thing (written in simple lowercase, no spaces/symbols)
COLUMN_SYNONYMS = {
    "Date": ["date", "transactiondate", "txndate", "postingdate", "valuedate"],
    "Description": ["description", "transactiondescription", "details", "narration",
                    "particulars", "memo", "remarks", "item"],
    "Amount": ["amount", "amt", "amountpkr", "transactionamount", "value"],
    "Type": ["type", "transactiontype", "txntype"],
    "Payment_Method": ["paymentmethod", "paymentmode", "paidvia", "mode", "method"],
    "Party": ["party", "customer", "vendor", "supplier", "customervendor",
              "customersupplier", "payee", "payer", "name"],
    "Category": ["category", "accountcategory"],
}

# Words people use for the transaction type
TYPE_LOOKUP = {
    "income": "Income", "sale": "Income", "sales": "Income", "revenue": "Income",
    "credit": "Income", "cr": "Income", "receipt": "Income", "received": "Income",
    "inflow": "Income", "deposit": "Income",
    "expense": "Expense", "expenses": "Expense", "debit": "Expense", "dr": "Expense",
    "payment": "Expense", "paid": "Expense", "purchase": "Expense", "cost": "Expense",
    "outflow": "Expense", "withdrawal": "Expense",
    "asset": "Asset", "assets": "Asset",
    "liability": "Liability", "liabilities": "Liability",
}


class FileProcessingError(Exception):
    """A problem with the uploaded file that we can explain to the user."""


@dataclass
class CleanResult:
    valid: pd.DataFrame      # rows that passed all checks
    issues: pd.DataFrame     # rows that failed, with the reason
    warnings: List[str]      # things to know but not blocking
    total_rows: int


def _normalize_name(name) -> str:
    """'Payment Method' -> 'paymentmethod'"""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# ---------------------------------------------------------------- reading
def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Read a .csv or .xlsx upload into a DataFrame (everything kept as raw values)."""
    name = str(getattr(uploaded_file, "name", "")).lower()
    if not name.endswith((".csv", ".xlsx")):
        raise FileProcessingError("Invalid file type. Please upload a .csv or .xlsx file.")

    data = uploaded_file.getvalue()
    if len(data) == 0:
        raise FileProcessingError("The file is empty.")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise FileProcessingError(f"The file is larger than {MAX_FILE_MB} MB.")

    try:
        if name.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(data), dtype=str, encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(data), dtype=str, encoding="latin-1")
        else:
            df = pd.read_excel(io.BytesIO(data), dtype=object, engine="openpyxl")
    except pd.errors.EmptyDataError:
        raise FileProcessingError("The file has no readable data.")
    except Exception as exc:
        logger.warning("File read failed: %s", type(exc).__name__)
        raise FileProcessingError(
            "Could not read the file. Please make sure it is a valid CSV or Excel file.") from exc

    df = df.dropna(how="all")                       # remove completely blank rows
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise FileProcessingError("The file has a header but no transaction rows.")
    return df


# ---------------------------------------------------------------- column matching
def map_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """Rename columns to our standard names.
    Returns (renamed data, {your column: standard column}, missing required columns)."""
    mapping: Dict[str, str] = {}
    used = set()
    for col in df.columns:
        norm = _normalize_name(col)
        for standard, synonyms in COLUMN_SYNONYMS.items():
            if norm in synonyms and standard not in used:
                mapping[col] = standard
                used.add(standard)
                break
    renamed = df[list(mapping.keys())].rename(columns=mapping)
    missing = [c for c in REQUIRED_COLUMNS if c not in renamed.columns]
    return renamed, mapping, missing


# ---------------------------------------------------------------- converters
def parse_dates(series: pd.Series) -> pd.Series:
    """Convert to dates. Day comes first: 05-10-2026 means 5 October 2026."""
    try:
        return pd.to_datetime(series, dayfirst=True, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(series, dayfirst=True, errors="coerce")


def _to_number(value) -> float:
    """Turn 'Rs. 12,500' or '12500' or 12500 into 12500.0 (or NaN if impossible)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = re.sub(r"(?i)pkr|rs\.?|rupees", "", text)   # remove currency words
    text = re.sub(r"[^0-9.]", "", text)                # keep digits and dot only
    if text in ("", "."):
        return np.nan
    try:
        number = float(text)
    except ValueError:
        return np.nan
    return -number if negative else number


def parse_amounts(series: pd.Series) -> pd.Series:
    return series.map(_to_number).astype(float)


def normalize_type(value) -> str:
    """Map many words to Income / Expense / Asset / Liability, else 'Unknown'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    key = re.sub(r"[^a-z]", "", str(value).lower())
    return TYPE_LOOKUP.get(key, "Unknown")


def _clean_text(series: pd.Series) -> pd.Series:
    return (series.fillna("").astype(str).str.strip()
            .replace({"nan": "", "None": "", "NaT": ""}))


# ---------------------------------------------------------------- validation
def clean_transactions(df: pd.DataFrame) -> CleanResult:
    """Check every row. Bad rows go to 'issues'; good rows go to 'valid'.
    One bad row never stops the others."""
    work = df.copy()
    for col in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
        if col not in work.columns:
            work[col] = np.nan

    issues: List[dict] = []

    def flag(mask: pd.Series, message: str) -> None:
        for idx in work.index[mask]:
            issues.append({"Row": int(idx) + 2, "Problem": message})  # +2 = header + 1-based

    # Description
    desc = work["Description"].fillna("").astype(str).str.strip()
    desc_bad = desc.eq("") | desc.str.lower().eq("nan")
    flag(desc_bad, "Missing description")

    # Date
    dates = parse_dates(work["Date"])
    date_missing = work["Date"].isna() | work["Date"].astype(str).str.strip().eq("")
    date_invalid = (dates.isna() & ~date_missing) | (dates.dt.year < 2000) | (dates.dt.year > 2100)
    flag(date_missing, "Missing date")
    flag(date_invalid & ~date_missing, "Invalid date (expected day-month-year, e.g. 05-10-2026)")

    # Amount
    amounts = parse_amounts(work["Amount"])
    amount_missing = work["Amount"].isna() | work["Amount"].astype(str).str.strip().eq("")
    amount_invalid = amounts.isna() & ~amount_missing
    amount_nonpositive = amounts.notna() & (amounts <= 0)
    flag(amount_missing, "Missing amount")
    flag(amount_invalid, "Invalid amount (not a number)")
    flag(amount_nonpositive, "Amount must be greater than zero (use Type for direction)")

    bad = (desc_bad | date_missing | date_invalid | amount_missing
           | amount_invalid | amount_nonpositive)
    good = ~bad

    valid = pd.DataFrame({
        "Date": dates[good].dt.strftime("%Y-%m-%d"),
        "Description": desc[good],
        "Amount": amounts[good].round(2),
        "Type": work.loc[good, "Type"].map(normalize_type),
        "Payment_Method": _clean_text(work.loc[good, "Payment_Method"]),
        "Party": _clean_text(work.loc[good, "Party"]),
        "Category": _clean_text(work.loc[good, "Category"]),
    }).reset_index(drop=True)

    warnings: List[str] = []
    unknown = int((valid["Type"] == "Unknown").sum())
    if unknown:
        warnings.append(f"{unknown} row(s) have a missing or unrecognised Type. "
                        "They are saved as 'Unknown' and can be fixed in review.")

    issues_df = (pd.DataFrame(issues, columns=["Row", "Problem"])
                 .sort_values("Row").reset_index(drop=True))
    logger.info("Validated %d rows: %d valid, %d with problems",
                len(work), len(valid), int(bad.sum()))
    return CleanResult(valid=valid, issues=issues_df, warnings=warnings, total_rows=len(work))


def mark_duplicates(df: pd.DataFrame, existing_keys: Set[str]) -> pd.DataFrame:
    """Add a 'Duplicate_Reason' column ('' means not a duplicate)."""
    out = df.copy()
    seen: Set[str] = set()
    reasons = []
    for d, desc, amt, party in zip(out["Date"], out["Description"], out["Amount"], out["Party"]):
        key = transaction_key(d, desc, amt, party)
        if key in existing_keys:
            reasons.append("Already saved in database")
        elif key in seen:
            reasons.append("Repeated inside this file")
        else:
            reasons.append("")
        seen.add(key)
    out["Duplicate_Reason"] = reasons
    return out
