"""MVP keyword rules that suggest a category. Phase 4 adds AI on top of this."""
import re
from typing import Optional, Tuple

# (keywords, type, category, subcategory). The FIRST matching rule wins, so order matters.
RULES = [
    (("bank service", "bank charge", "bank fee"), "Expense", "Bank Charges", ""),
    (("electricity", "pesco", "wapda", "lesco"), "Expense", "Utilities", "Electricity"),
    (("gas bill", "sui gas", "sngpl", "water bill"), "Expense", "Utilities", "Gas/Water"),
    (("internet", "ptcl", "telephone", "phone bill", "mobile load"), "Expense", "Telephone/Internet", ""),
    (("salary", "salaries", "wages"), "Expense", "Salaries", ""),
    (("rent",), "Expense", "Rent", ""),
    (("petrol", "diesel", "fuel"), "Expense", "Fuel", ""),
    (("transport", "delivery van", "van charges", "van hire", "freight", "courier", "rickshaw"),
     "Expense", "Transportation", ""),
    (("facebook", "ads", "ad campaign", "advert", "marketing", "promotion", "banner"),
     "Expense", "Marketing", ""),
    (("repair", "maintenance"), "Expense", "Repairs & Maintenance", ""),
    (("stationery", "office supplies", "printer"), "Expense", "Office Supplies", ""),
    (("stock", "inventory", "supplier", "wholesale", "purchase"), "Expense", "Inventory Purchase", ""),
    (("miscellaneous", "misc", "other expense"), "Expense", "Other Expenses", ""),
    (("service charges", "service revenue", "consultancy", "freelance", "commission"),
     "Income", "Service Revenue", ""),
    (("interest", "rebate", "refund received"), "Income", "Other Income", ""),
    (("sale", "sales", "sold", "revenue", "received payment", "payment received", "customer payment"),
     "Income", "Sales Revenue", ""),
]

KNOWN_TYPES = ("Income", "Expense", "Asset", "Liability")


def suggest_category(description: str, tx_type: str) -> Optional[Tuple[str, str, str]]:
    """Return (type, category, subcategory) or None if no rule matches.
    If the transaction already has a known Type, only rules of that Type are used."""
    text = str(description).lower()
    for keywords, rule_type, category, subcategory in RULES:
        if tx_type in KNOWN_TYPES and tx_type != rule_type:
            continue
        # \b = start of a word, so 'rent' matches 'shop rent' but not 'current'
        if any(re.search(r"\b" + re.escape(k), text) for k in keywords):
            return rule_type, category, subcategory
    return None
