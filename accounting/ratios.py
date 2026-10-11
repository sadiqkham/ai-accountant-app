"""Financial ratios. Calculated only when enough data exists. No guessing."""
from typing import Dict, List, Optional

from accounting.calculations import percentage, safe_divide


def _ratio(name: str, value: Optional[float], unit: str, formula: str,
           meaning: str = "", missing: str = "") -> Dict:
    return {"name": name, "value": value, "unit": unit, "formula": formula,
            "meaning": meaning, "missing": missing, "available": value is not None}


def net_profit_margin(pl: Dict, currency: str) -> Dict:
    value = pl["net_margin"]
    formula = "Net Profit / Revenue × 100"
    if value is None:
        return _ratio("Net Profit Margin", None, "%", formula,
                      missing="No revenue is recorded in this period, so the margin cannot be calculated.")
    if value >= 0:
        meaning = (f"The business earns about {currency} {value:,.1f} of net profit for every "
                   f"{currency} 100 of revenue, based on the recorded data.")
    else:
        meaning = (f"The business lost about {currency} {abs(value):,.1f} for every "
                   f"{currency} 100 of revenue, based on the recorded data.")
    return _ratio("Net Profit Margin", value, "%", formula, meaning)


def expense_ratio(pl: Dict, currency: str) -> Dict:
    value = percentage(pl["total_expenses"], pl["total_revenue"])
    formula = "Total Expenses / Revenue × 100"
    if value is None:
        return _ratio("Expense Ratio", None, "%", formula,
                      missing="No revenue is recorded in this period, so this ratio cannot be calculated.")
    meaning = (f"The business spends about {currency} {value:,.1f} on expenses for every "
               f"{currency} 100 of revenue, based on the recorded data.")
    return _ratio("Expense Ratio", value, "%", formula, meaning)


def current_ratio(current_assets: Optional[float], current_liabilities: Optional[float],
                  currency: str) -> Dict:
    formula = "Current Assets / Current Liabilities"
    if current_assets is None or current_liabilities is None:
        return _ratio("Current Ratio", None, "x", formula,
                      missing="Insufficient data. Enter current assets and current liabilities in Settings.")
    value = safe_divide(current_assets, current_liabilities)
    if value is None:
        return _ratio("Current Ratio", None, "x", formula,
                      missing="Current liabilities are zero, so this ratio cannot be calculated.")
    meaning = (f"For every {currency} 1 of current liabilities, the business has {currency} {value:,.2f} "
               "of current assets (using the figures you entered in Settings).")
    return _ratio("Current Ratio", value, "x", formula, meaning)


def compute_all_ratios(pl: Dict, settings: Dict[str, Optional[float]], currency: str) -> List[Dict]:
    return [
        net_profit_margin(pl, currency),
        expense_ratio(pl, currency),
        current_ratio(settings.get("current_assets"), settings.get("current_liabilities"), currency),
    ]
