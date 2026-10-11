"""Creates a clearly synthetic sample dataset (PKR) for testing."""
import random
from datetime import date, timedelta

import pandas as pd


def generate_sample_dataframe(seed: int = 42) -> pd.DataFrame:
    """Return about 115 fake transactions, including duplicates and unusual ones."""
    rng = random.Random(seed)  # fixed seed = same data every time
    rows = []

    def add(day, description, amount, ttype, method, party=""):
        rows.append({
            "Date": day.strftime("%d-%m-%Y"),   # day-month-year, like Pakistan
            "Description": description,
            "Amount": int(amount),
            "Type": ttype,
            "Payment_Method": method,
            "Party": party,
        })

    customers = ["ABC Store", "XYZ Traders", "Ali Enterprises", "Khan Brothers"]
    suppliers = ["Hayat Wholesale", "Peshawar Foods", "Kohat Distributors"]

    day = date(2026, 8, 1)
    end = date(2026, 10, 5)
    while day <= end:
        if day.weekday() != 4:  # shop closed on Fridays
            add(day, rng.choice(["Daily retail sales", "Cash sales - counter", "Grocery sales"]),
                round(rng.randint(35000, 95000), -2), "Income",
                rng.choice(["Cash", "Cash", "Bank"]), "Walk-in customers")
        if day.day == 1:
            add(day, "Paid shop rent", 60000, "Expense", "Bank", "Landlord")
        if day.day == 7 or day.day == 20:
            c = rng.choice(customers)
            add(day, f"Received payment from {c}", round(rng.randint(15000, 60000), -2),
                "Income", "Bank", c)
        if day.day == 9 or day.day == 23:
            s = rng.choice(suppliers)
            add(day, f"Paid supplier {s}", round(rng.randint(40000, 90000), -2),
                "Expense", "Bank", s)
        if day.day == 10:
            add(day, "Paid electricity bill - PESCO", rng.randint(11000, 14500),
                "Expense", "Bank", "PESCO")
        if day.day == 12:
            add(day, "Paid internet bill - PTCL", 3500, "Expense", "Bank", "PTCL")
        if day.day == 15:
            add(day, "Facebook ads payment", rng.randint(8000, 12000),
                "Expense", "Bank", "Meta")
        if day.day == 18:
            add(day, "Home delivery service charges", round(rng.randint(15000, 25000), -2),
                "Income", "Cash", "Customers")
        if day.day == 25:
            add(day, "Bank service charges", rng.randint(400, 900), "Expense", "Bank", "Bank")
        if day.day == 28:
            add(day, "Paid monthly salaries to staff", 135000, "Expense", "Bank", "Staff")
        if day.weekday() == 0:   # Monday
            add(day, "Petrol for delivery bike", rng.randint(4000, 6500),
                "Expense", "Cash", "Petrol pump")
        if day.weekday() == 2:   # Wednesday
            s = rng.choice(suppliers)
            add(day, f"Purchased stock from {s}", round(rng.randint(60000, 120000), -2),
                "Expense", "Bank", s)
        if day.weekday() == 5:   # Saturday
            add(day, "Delivery van charges", rng.randint(3000, 6000),
                "Expense", "Cash", "Transporter")
        day += timedelta(days=1)

    # ---- Records added on purpose for anomaly testing (Phase 5) ----
    add(date(2026, 9, 18), "Transport charges - delivery van hire", 180000,
        "Expense", "Cash", "Transporter")                       # unusually high
    add(date(2026, 9, 14), "Facebook ad campaign", 150000,
        "Expense", "Bank", "Meta")                              # marketing spike
    add(date(2026, 9, 25), "Miscellaneous payment", 500000,
        "Expense", "Cash", "")                                  # large round number
    add(date(2026, 9, 30), "Bulk order sale", 450000,
        "Income", "Bank", "Khan Brothers")                      # unusually high sale
    # Exact duplicates of existing rows
    electricity = next(r for r in rows if r["Description"].startswith("Paid electricity")
                       and r["Date"] == "10-09-2026")
    rows.append(dict(electricity))
    rows.append(dict(rows[0]))
    rows.append(dict(rows[5]))

    return pd.DataFrame(rows)
