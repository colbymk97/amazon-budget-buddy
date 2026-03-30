"""Batch AI categorization of retailer transactions using Actual Budget categories.

Uses the Anthropic (Claude) API to classify uncategorized transactions in a
single request for efficiency.  Requires the ``anthropic`` package::

    pip install anthropic
    # or: pip install "amazon-spending[ai]"

The caller must supply an ``ANTHROPIC_API_KEY`` environment variable.
"""
from __future__ import annotations

import json
import re
from typing import Any


def batch_categorize(
    transactions: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    *,
    chunk_size: int = 200,
) -> list[dict[str, str]]:
    """Categorize *transactions* against Actual Budget *categories* via Claude.

    Parameters
    ----------
    transactions:
        Each dict must have at least ``retailer_txn_id``, ``amount_cents``,
        ``txn_date``, and ``item_titles`` (pipe-separated item names).
    categories:
        Each dict has ``id``, ``name``, and ``group`` from Actual Budget.
    chunk_size:
        Max transactions per LLM call to stay within context limits.

    Returns
    -------
    list of ``{"txn_id": str, "category_id": str, "category_name": str}``
    """
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic is not installed. Run: pip install anthropic"
            " (or: pip install \"amazon-spending[ai]\")"
        ) from exc

    if not transactions or not categories:
        return []

    results: list[dict[str, str]] = []
    for start in range(0, len(transactions), chunk_size):
        chunk = transactions[start : start + chunk_size]
        chunk_results = _categorize_chunk(anthropic.Anthropic(), chunk, categories)
        results.extend(chunk_results)
    return results


def _categorize_chunk(
    client: Any,
    transactions: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Send one batch to Claude and parse the response."""
    cat_lines = "\n".join(
        f'  {{"id": "{c["id"]}", "group": "{c["group"]}", "name": "{c["name"]}"}}'
        for c in categories
    )
    txn_lines = "\n".join(
        f'  {{"txn_id": "{t["retailer_txn_id"]}", "amount": "${abs(t["amount_cents"]) / 100:.2f}", '
        f'"date": "{t["txn_date"]}", "items": "{t["item_titles"]}"}}'
        for t in transactions
    )

    prompt = f"""You are a financial categorization assistant. Given a list of budget categories from Actual Budget and a list of Amazon/retailer transactions with their purchased items, assign the single best matching category to each transaction.

CATEGORIES (from Actual Budget):
[
{cat_lines}
]

TRANSACTIONS TO CATEGORIZE:
[
{txn_lines}
]

For each transaction, pick the most appropriate category based on the item descriptions. Return ONLY a JSON array with no additional text:
[
  {{"txn_id": "...", "category_id": "...", "category_name": "..."}}
]

Rules:
- Use exact category_id and category_name values from the CATEGORIES list above.
- Every transaction must get exactly one category.
- If no category fits well, use the most general/closest match available.
- Return valid JSON only, no markdown fences, no explanation."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if the model included them despite instructions
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    valid: list[dict[str, str]] = []
    cat_ids = {c["id"] for c in categories}
    for item in parsed:
        if isinstance(item, dict) and item.get("txn_id") and item.get("category_id") in cat_ids:
            valid.append({
                "txn_id": str(item["txn_id"]),
                "category_id": str(item["category_id"]),
                "category_name": str(item.get("category_name", "")),
            })
    return valid
