"""Month-to-month changes, calculated by Python."""
import pandas as pd

from accounting.calculations import percentage

COLUMNS = ["category", "previous", "latest", "change", "change_pct"]


def expense_category_changes(df: pd.DataFrame):
    """Compare each expense category in the last two months of data.
    Returns (table, previous_month, latest_month). Table is empty if there are fewer than 2 months."""
    expenses = df[df["transaction_type"] == "Expense"]
    months = sorted(expenses["month"].unique())
    if len(months) < 2:
        return pd.DataFrame(columns=COLUMNS), None, None
    previous_month, latest_month = months[-2], months[-1]
    pivot = (expenses[expenses["month"].isin([previous_month, latest_month])]
             .pivot_table(index="category", columns="month", values="amount",
                          aggfunc="sum", fill_value=0))
    table = pd.DataFrame({"category": pivot.index,
                          "previous": pivot[previous_month].values,
                          "latest": pivot[latest_month].values})
    table["change"] = table["latest"] - table["previous"]
    table["change_pct"] = [percentage(c, p) for c, p in zip(table["change"], table["previous"])]
    return table.sort_values("change", ascending=False).reset_index(drop=True), previous_month, latest_month
