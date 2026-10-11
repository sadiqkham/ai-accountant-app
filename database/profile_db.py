"""Saves the business profile in the database so it survives page reloads."""
from typing import Dict

from database.db import get_connection

DEFAULT_PROFILE = {"name": "My Business", "type": "Retail", "industry": "", "city": "", "currency": "PKR"}


def get_profile() -> Dict[str, str]:
    with get_connection() as conn:
        row = conn.execute("""SELECT business_name, business_type, industry, city, currency
                              FROM businesses WHERE id = 1""").fetchone()
    if not row:
        return dict(DEFAULT_PROFILE)
    name, btype, industry, city, currency = row
    return {"name": name or DEFAULT_PROFILE["name"], "type": btype or DEFAULT_PROFILE["type"],
            "industry": industry or "", "city": city or "", "currency": currency or "PKR"}


def save_profile(profile: Dict[str, str]) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE businesses SET business_name = ?, business_type = ?, industry = ?, city = ?,
               currency = ? WHERE id = 1""",
            (profile["name"], profile["type"], profile["industry"], profile["city"], profile["currency"]))
        if cursor.rowcount == 0:
            conn.execute(
                """INSERT INTO businesses (id, business_name, business_type, industry, city, currency)
                   VALUES (1, ?, ?, ?, ?, ?)""",
                (profile["name"], profile["type"], profile["industry"], profile["city"], profile["currency"]))
