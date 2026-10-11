"""Shared constants and small helper functions."""
from typing import Dict, List

# What kind of transaction is it?
TRANSACTION_TYPES = ["Income", "Expense", "Asset", "Liability"]

# Fixed category list. The AI (Phase 4) must choose from this list only.
CATEGORIES: Dict[str, List[str]] = {
    "Income": ["Sales Revenue", "Service Revenue", "Other Income"],
    "Expense": ["Rent", "Salaries", "Utilities", "Transportation", "Fuel",
                "Marketing", "Office Supplies", "Telephone/Internet",
                "Repairs & Maintenance", "Bank Charges", "Inventory Purchase",
                "Other Expenses"],
    "Asset": ["Inventory", "Equipment", "Accounts Receivable"],
    "Liability": ["Accounts Payable", "Loan", "Accrued Expenses"],
}
ALL_CATEGORIES = [c for group in CATEGORIES.values() for c in group]

# How the money moved (this is NOT a category)
PAYMENT_METHODS = ["Cash", "Bank", "Mobile Wallet", "Cheque", "Credit", "Other"]


def transaction_key(date: str, description: str, amount, party) -> str:
    """Build a text 'fingerprint' used to spot duplicate transactions."""
    return (f"{str(date).strip()}|{str(description).strip().lower()}|"
            f"{float(amount):.2f}|{str(party or '').strip().lower()}")
