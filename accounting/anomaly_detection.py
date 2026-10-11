"""Anomaly detection with rules and statistics.
NO AI decides what is unusual. A flag means 'please review', never 'fraud'."""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from utils.helpers import transaction_key

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# THRESHOLDS: change these numbers to make the checks stricter or looser
# ------------------------------------------------------------------
MIN_GROUP_FOR_IQR = 8                 # groups this big use the IQR method
IQR_MEDIUM, IQR_HIGH = 1.5, 3.0       # fence = Q3 + k * IQR
MEDIAN_RATIO_MEDIUM, MEDIAN_RATIO_HIGH = 1.5, 2.5   # must ALSO be this many times the median
SMALL_GROUP_RATIO_MEDIUM, SMALL_GROUP_RATIO_HIGH = 3.0, 6.0
NEAR_DUPLICATE_DAYS = 3
SPIKE_RATIO_MEDIUM, SPIKE_RATIO_HIGH = 2.0, 3.0     # month total vs recent average
SPIKE_MIN_INCREASE = 10_000
NEW_CATEGORY_MIN, NEW_CATEGORY_HIGH = 50_000, 250_000
BUSY_DAY_SIGMA, BUSY_DAY_MIN_COUNT = 3.0, 5
SAME_DAY_PARTY_COUNT = 3
ROUND_MIN, ROUND_STEP = 100_000, 50_000
LARGE_NO_PARTY = 100_000
NEW_PARTY_RATIO, NEW_PARTY_MIN, NEW_PARTY_MIN_TRANSACTIONS = 3.0, 25_000, 30

LEVEL_ORDER = {"High": 0, "Medium": 1, "Low": 2}
SEVERITY_NAME = {1: "Low", 2: "Medium", 3: "High"}
FLAG_COLUMNS = ["id", "date", "description", "amount", "transaction_type", "category",
                "party", "status", "risk_level", "risk_points", "rules", "reason"]
ALERT_COLUMNS = ["month", "category", "amount", "typical_before", "change_pct",
                 "risk_level", "message"]


@dataclass
class Finding:
    tx_id: int
    rule: str
    severity: int      # 1 = low, 2 = medium, 3 = high
    reason: str


@dataclass
class AnomalyResult:
    flags: pd.DataFrame            # one row per flagged transaction
    category_alerts: pd.DataFrame  # one row per category-month spike
    analysed: int                  # how many transactions were checked
    message: str = ""


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.0f}"


# ---------------------------------------------------------------- Check 1: high amounts
def rule_high_amount(df: pd.DataFrame, currency: str) -> List[Finding]:
    findings: List[Finding] = []
    data = df[df["category"] != "Uncategorized"]
    for (_, category), group in data.groupby(["transaction_type", "category"]):
        n = len(group)
        if n < 2:
            continue
        amounts = group["amount"]
        if n >= MIN_GROUP_FOR_IQR:
            q1, q3 = amounts.quantile(0.25), amounts.quantile(0.75)
            iqr, median = q3 - q1, float(amounts.median())
            if median <= 0:
                continue
            for row in group.itertuples():
                if row.amount > q3 + IQR_HIGH * iqr and row.amount >= MEDIAN_RATIO_HIGH * median:
                    severity = 3
                elif row.amount > q3 + IQR_MEDIUM * iqr and row.amount >= MEDIAN_RATIO_MEDIUM * median:
                    severity = 2
                else:
                    continue
                findings.append(Finding(
                    int(row.id), "Unusually high amount", severity,
                    f"{_money(row.amount, currency)} is about {row.amount / median:.1f} times the typical "
                    f"{category} amount ({_money(median, currency)}, based on {n} transactions)."))
        else:
            # Too few transactions for IQR: compare with the median of the OTHERS
            for row in group.itertuples():
                median = float(amounts.drop(row.Index).median())
                if median <= 0:
                    continue
                ratio = row.amount / median
                if ratio >= SMALL_GROUP_RATIO_HIGH:
                    severity = 3
                elif ratio >= SMALL_GROUP_RATIO_MEDIUM:
                    severity = 2
                else:
                    continue
                findings.append(Finding(
                    int(row.id), "Unusually high amount", severity,
                    f"{_money(row.amount, currency)} is {ratio:.1f} times the typical {category} amount "
                    f"({_money(median, currency)}, based on the other {n - 1} transaction(s))."))
    return findings


# ---------------------------------------------------------------- Check 2: duplicates
def rule_duplicates(df: pd.DataFrame, currency: str) -> List[Finding]:
    findings: List[Finding] = []
    dates = df["date"].dt.strftime("%Y-%m-%d")
    keys = [transaction_key(d, desc, amt, party)
            for d, desc, amt, party in zip(dates, df["description"], df["amount"], df["party"])]
    work = df.assign(_key=keys)

    # Exact duplicates: the later copies are flagged
    for _, group in work.groupby("_key"):
        if len(group) > 1:
            ids = sorted(int(i) for i in group["id"])
            for later in ids[1:]:
                findings.append(Finding(later, "Possible duplicate", 2,
                                        f"Same date, description, amount and party as transaction #{ids[0]}."))

    # Near duplicates: same description and amount a few days apart
    work["_near"] = (work["description"].str.lower().str.strip() + "|"
                     + work["amount"].round(2).astype(str) + "|"
                     + work["party"].str.lower().str.strip())
    for _, group in work.groupby("_near"):
        if len(group) < 2 or len(group) > 3:   # many repeats = a normal recurring pattern
            continue
        group = group.sort_values(["date", "id"]).drop_duplicates("date")
        previous = None
        for row in group.itertuples():
            if previous is not None:
                gap = (row.date - previous.date).days
                if 1 <= gap <= NEAR_DUPLICATE_DAYS:
                    findings.append(Finding(int(row.id), "Repeated within days", 1,
                                            f"Same description and amount as transaction #{int(previous.id)} "
                                            f"only {gap} day(s) earlier."))
            previous = row
    return findings


# ---------------------------------------------------------------- Check 3: category spikes
def rule_category_spikes(df: pd.DataFrame, currency: str):
    """Returns (findings for transactions, alerts for the category table)."""
    findings: List[Finding] = []
    alerts: List[Dict] = []
    expenses = df[(df["transaction_type"] == "Expense") & (df["category"] != "Uncategorized")]
    if expenses.empty:
        return findings, alerts
    monthly = expenses.pivot_table(index="category", columns="month", values="amount",
                                   aggfunc="sum", fill_value=0)
    months = sorted(monthly.columns)
    for position in range(1, len(months)):
        month = months[position]
        prior = months[max(0, position - 3):position]
        for category in monthly.index:
            amount = float(monthly.at[category, month])
            baseline = float(monthly.loc[category, prior].mean())
            if amount <= 0 or amount - baseline < SPIKE_MIN_INCREASE:
                continue
            if baseline == 0:
                if amount < NEW_CATEGORY_MIN:
                    continue
                severity = 3 if amount >= NEW_CATEGORY_HIGH else 2
                change_pct = None
                text = (f"{category} spending of {_money(amount, currency)} in {month} is new: nothing was "
                        f"recorded in the previous {len(prior)} month(s).")
            else:
                ratio = amount / baseline
                if ratio < SPIKE_RATIO_MEDIUM:
                    continue
                severity = 3 if ratio >= SPIKE_RATIO_HIGH else 2
                change_pct = round((ratio - 1) * 100, 1)
                text = (f"{category} spending in {month} ({_money(amount, currency)}) is {ratio:.1f} times "
                        f"the recent monthly average ({_money(baseline, currency)}).")
            alerts.append({"month": month, "category": category, "amount": round(amount, 2),
                           "typical_before": round(baseline, 2), "change_pct": change_pct,
                           "risk_level": SEVERITY_NAME[severity], "message": text})
            # Attach the finding to the biggest transactions behind the spike
            biggest = expenses[(expenses["category"] == category) & (expenses["month"] == month)].nlargest(3, "amount")
            for row in biggest.itertuples():
                if row.amount >= 0.2 * amount:
                    findings.append(Finding(int(row.id), "Category spending spike", severity, text))
    return findings, alerts


# ---------------------------------------------------------------- Check 4: frequency
def rule_frequency(df: pd.DataFrame, currency: str) -> List[Finding]:
    findings: List[Finding] = []
    daily = df.groupby("date").size()
    if len(daily) == 0:
        return findings
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    counts = daily.reindex(full_range, fill_value=0)
    if len(counts) >= 14:
        mean, std = float(counts.mean()), float(counts.std())
        if std > 0:
            limit = mean + BUSY_DAY_SIGMA * std
            for day, count in counts[(counts > limit) & (counts >= BUSY_DAY_MIN_COUNT)].items():
                for tx_id in df.loc[df["date"] == day, "id"]:
                    findings.append(Finding(int(tx_id), "Unusual activity level", 1,
                                            f"{int(count)} transactions on {day:%d %b %Y}, much busier "
                                            f"than the usual {mean:.1f} per day."))
    expenses = df[(df["transaction_type"] == "Expense") & (df["party"].str.strip() != "")]
    expenses = expenses.assign(_party=expenses["party"].str.strip().str.lower())
    for (_, _), group in expenses.groupby(["date", "_party"]):
        if len(group) >= SAME_DAY_PARTY_COUNT:
            for row in group.itertuples():
                findings.append(Finding(int(row.id), "Unusual activity level", 1,
                                        f"{len(group)} expense transactions with '{row.party.strip()}' "
                                        "on the same day."))
    return findings


# ---------------------------------------------------------------- Check 5: round numbers
def rule_round_numbers(df: pd.DataFrame, currency: str) -> List[Finding]:
    findings: List[Finding] = []
    candidates = df[(df["amount"] >= ROUND_MIN) & ((df["amount"] % ROUND_STEP).abs() < 0.005)]
    repeats = df.groupby(["category", "amount"]).size()
    for row in candidates.itertuples():
        if repeats.get((row.category, row.amount), 0) >= 3:   # e.g. monthly rent: normal
            continue
        findings.append(Finding(int(row.id), "Large round amount", 1,
                                f"{_money(row.amount, currency)} is a large, round amount. "
                                "Round figures are worth matching to an invoice or receipt."))
    return findings


# ---------------------------------------------------------------- Check 6: customer/vendor
def rule_counterparty(df: pd.DataFrame, currency: str) -> List[Finding]:
    findings: List[Finding] = []
    missing = df[(df["transaction_type"] == "Expense") & (df["amount"] >= LARGE_NO_PARTY)
                 & (df["party"].str.strip() == "")]
    for row in missing.itertuples():
        findings.append(Finding(int(row.id), "Missing customer/vendor", 1,
                                f"Large expense ({_money(row.amount, currency)}) with no vendor recorded."))

    if len(df) >= NEW_PARTY_MIN_TRANSACTIONS:
        keys = df["party"].str.strip().str.lower()
        counts = keys[keys != ""].value_counts()
        typical = df.groupby("transaction_type")["amount"].median()
        for row, key in zip(df.itertuples(), keys):
            if key and counts.get(key, 0) == 1:
                median = float(typical.get(row.transaction_type, 0))
                if row.amount >= NEW_PARTY_MIN and median > 0 and row.amount >= NEW_PARTY_RATIO * median:
                    findings.append(Finding(
                        int(row.id), "New customer/vendor", 1,
                        f"First and only transaction with '{row.party.strip()}', and the amount is large "
                        f"compared with typical {row.transaction_type.lower()} amounts."))
    return findings


SIMPLE_RULES = [("high amounts", rule_high_amount), ("duplicates", rule_duplicates),
                ("frequency", rule_frequency), ("round numbers", rule_round_numbers),
                ("customer/vendor", rule_counterparty)]


# ---------------------------------------------------------------- put it all together
def _risk_level(findings: List[Finding]):
    points = sum(f.severity for f in findings)
    top = max(f.severity for f in findings)
    if top >= 3 or points >= 5:
        return "High", points
    if top == 2 or points >= 2:
        return "Medium", points
    return "Low", points


def detect_anomalies(df: Optional[pd.DataFrame], currency: str = "PKR") -> AnomalyResult:
    """Run every check on prepared data (see calculations.prepare). Never crashes."""
    empty_flags = pd.DataFrame(columns=FLAG_COLUMNS)
    empty_alerts = pd.DataFrame(columns=ALERT_COLUMNS)
    if df is None or df.empty:
        return AnomalyResult(empty_flags, empty_alerts, 0, "No transactions to analyse yet.")
    work = df[df["transaction_type"].isin(["Income", "Expense"])].copy().reset_index(drop=True)
    if work.empty:
        return AnomalyResult(empty_flags, empty_alerts, 0, "No income or expense transactions to analyse.")
    work["party"] = work["party"].fillna("").astype(str)
    work["category"] = work["category"].fillna("Uncategorized")

    findings: List[Finding] = []
    alerts: List[Dict] = []
    failed: List[str] = []
    for name, rule in SIMPLE_RULES:
        try:
            findings.extend(rule(work, currency))
        except Exception:                       # one broken check must not stop the others
            logger.exception("Anomaly check failed: %s", name)
            failed.append(name)
    try:
        spike_findings, alerts = rule_category_spikes(work, currency)
        findings.extend(spike_findings)
    except Exception:
        logger.exception("Anomaly check failed: category spikes")
        failed.append("category spikes")

    by_transaction: Dict[int, List[Finding]] = {}
    for finding in findings:
        by_transaction.setdefault(finding.tx_id, []).append(finding)

    info = work.set_index("id")
    rows = []
    for tx_id, items in by_transaction.items():
        if tx_id not in info.index:
            continue
        record = info.loc[tx_id]
        level, points = _risk_level(items)
        ordered = sorted(items, key=lambda f: -f.severity)
        rows.append({
            "id": int(tx_id), "date": record["date"], "description": record["description"],
            "amount": float(record["amount"]), "transaction_type": record["transaction_type"],
            "category": record["category"], "party": record["party"], "status": record["status"],
            "risk_level": level, "risk_points": points,
            "rules": ", ".join(dict.fromkeys(f.rule for f in ordered)),
            "reason": " • ".join(dict.fromkeys(f.reason for f in ordered)),
        })
    flags = pd.DataFrame(rows, columns=FLAG_COLUMNS)
    if not flags.empty:
        flags["_order"] = flags["risk_level"].map(LEVEL_ORDER)
        flags = (flags.sort_values(["_order", "risk_points", "amount"], ascending=[True, False, False])
                 .drop(columns="_order").reset_index(drop=True))

    alerts_df = pd.DataFrame(alerts, columns=ALERT_COLUMNS)
    if not alerts_df.empty:
        alerts_df["_order"] = alerts_df["risk_level"].map(LEVEL_ORDER)
        alerts_df = (alerts_df.sort_values(["_order", "amount"], ascending=[True, False])
                     .drop(columns="_order").reset_index(drop=True))

    message = f"Some checks could not run: {', '.join(failed)}." if failed else ""
    logger.info("Anomaly detection: %d transactions checked, %d flagged", len(work), len(flags))
    return AnomalyResult(flags, alerts_df, len(work), message)


def filter_flags_by_period(flags: pd.DataFrame, start, end) -> pd.DataFrame:
    """Keep only flags whose transaction date is inside the chosen period."""
    if flags.empty:
        return flags
    mask = pd.Series(True, index=flags.index)
    if start is not None:
        mask &= flags["date"] >= start
    if end is not None:
        mask &= flags["date"] <= end
    return flags[mask].reset_index(drop=True)


def filter_alerts_by_period(alerts: pd.DataFrame, start, end) -> pd.DataFrame:
    if alerts.empty:
        return alerts
    mask = pd.Series(True, index=alerts.index)
    if start is not None:
        mask &= alerts["month"] >= start.strftime("%Y-%m")
    if end is not None:
        mask &= alerts["month"] <= end.strftime("%Y-%m")
    return alerts[mask].reset_index(drop=True)
