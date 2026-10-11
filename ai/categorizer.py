"""AI transaction categorization with strict validation of every answer."""
import json
import logging
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from ai import groq_client
from ai.prompts import CATEGORIZER_SYSTEM
from utils.helpers import ALL_CATEGORIES, CATEGORIES, TRANSACTION_TYPES

logger = logging.getLogger(__name__)

BATCH_SIZE = 15   # transactions per AI request
CATEGORY_TYPE = {cat: t for t, cats in CATEGORIES.items() for cat in cats}


def _match(value, options: List[str]) -> Optional[str]:
    """Case-insensitive match against an allowed list. Returns the official spelling."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().lower()
    for option in options:
        if option.lower() == wanted:
            return option
    return None


def validate_ai_result(entry, type_hint: str = "Unknown") -> Tuple[Optional[Dict], str]:
    """Check ONE AI answer. Returns (clean_result, '') or (None, reason_it_was_rejected)."""
    if not isinstance(entry, dict):
        return None, "reply item was not an object"
    raw_category = entry.get("category")
    if raw_category in (None, "", "null"):
        return None, "AI was not sure, so no category was suggested"
    category = _match(raw_category, ALL_CATEGORIES)
    if category is None:
        return None, f"'{raw_category}' is not in the allowed category list"
    category_type = CATEGORY_TYPE[category]

    stated_type = _match(entry.get("transaction_type"), TRANSACTION_TYPES)
    if stated_type is not None and stated_type != category_type:
        return None, "transaction type and category do not match"
    if type_hint in TRANSACTION_TYPES and type_hint != category_type:
        return None, f"suggestion conflicts with the existing type '{type_hint}'"

    try:
        confidence = float(entry.get("confidence"))
    except (TypeError, ValueError):
        return None, "confidence is not a number"
    if 1 < confidence <= 100:          # the AI wrote 96 instead of 0.96
        confidence /= 100
    if not 0 <= confidence <= 1:
        return None, "confidence is out of range"

    return {
        "transaction_type": category_type,
        "category": category,
        "subcategory": str(entry.get("subcategory") or "").strip()[:40],
        "confidence": round(confidence, 2),
        "reason": str(entry.get("reason") or "").strip()[:120],
    }, ""


def categorize_batch(items: List[Dict], ask: Optional[Callable] = None) -> Tuple[Dict[int, Dict], List[str]]:
    """Send one batch to the AI. Returns ({id: result}, [problems]).
    Raises GroqConfigError / AIError if the AI cannot be reached."""
    ask = ask or groq_client.chat_completion
    payload = [{"id": it["id"], "description": str(it["description"])[:200],
                "amount": it["amount"], "type_hint": it["type_hint"],
                "party": str(it.get("party", ""))[:60]} for it in items]
    messages = [
        {"role": "system", "content": CATEGORIZER_SYSTEM},
        {"role": "user", "content": "Classify these transactions. Respond with JSON only.\n"
                                    + json.dumps(payload, ensure_ascii=False)},
    ]
    text = ask(messages, json_mode=True, max_tokens=3000, temperature=0.0)

    data = groq_client.parse_json_reply(text)
    raw_results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(raw_results, list):
        return {}, ["The AI reply was not valid JSON, so this batch was skipped."]

    hints = {it["id"]: it["type_hint"] for it in items}
    results, problems = {}, []
    for entry in raw_results:
        if not isinstance(entry, dict):
            problems.append("A result was not an object")
            continue
        try:
            tx_id = int(entry.get("id"))
        except (TypeError, ValueError):
            problems.append("A result had no valid id")
            continue
        if tx_id not in hints:            # the AI invented an id
            problems.append(f"Ignored a result for unknown id {tx_id}")
            continue
        clean, problem = validate_ai_result(entry, hints[tx_id])
        if clean:
            results[tx_id] = clean
        else:
            problems.append(f"Transaction {tx_id}: {problem}")
    return results, problems


def categorize_dataframe(df: pd.DataFrame, progress: Optional[Callable[[int, int], None]] = None,
                         ask: Optional[Callable] = None) -> Dict:
    """Categorize many transactions in batches. Never crashes: failures are reported."""
    items = []
    for row in df.itertuples():
        hint = row.transaction_type if row.transaction_type in TRANSACTION_TYPES else "Unknown"
        items.append({"id": int(row.id), "description": str(row.description),
                      "amount": float(row.amount), "type_hint": hint, "party": str(row.party or "")})

    suggested: Dict[int, Dict] = {}
    problems: List[str] = []
    stopped = None
    for start in range(0, len(items), BATCH_SIZE):
        try:
            results, batch_problems = categorize_batch(items[start:start + BATCH_SIZE], ask)
        except (groq_client.AIError, groq_client.GroqConfigError) as exc:
            stopped = str(exc)
            break
        suggested.update(results)
        problems.extend(batch_problems)
        if progress:
            progress(min(start + BATCH_SIZE, len(items)), len(items))
    logger.info("AI categorization: %d suggested, %d problems", len(suggested), len(problems))
    return {"suggested": suggested, "problems": problems, "stopped": stopped}
