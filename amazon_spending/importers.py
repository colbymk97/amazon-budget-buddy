from __future__ import annotations

import csv
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

REQUIRED_TRANSACTION_HEADERS = {
    "transaction_id",
    "posted_date",
    "amount",
    "merchant_raw",
}


def to_cents(value: str) -> int:
    dec = Decimal(value.strip())
    cents = (dec.copy_abs() * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def import_transactions_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    account_id: str | None = None,
) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("Transactions CSV has no headers")

        missing = REQUIRED_TRANSACTION_HEADERS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Transactions CSV missing required headers: {sorted(missing)}")

        rows = []
        for row in reader:
            txn_id = row["transaction_id"].strip()
            if not txn_id:
                continue
            rows.append(
                (
                    txn_id,
                    row["posted_date"].strip(),
                    to_cents(row["amount"]),
                    row["merchant_raw"].strip(),
                    row.get("description", "").strip() or None,
                    row.get("currency", "USD").strip() or "USD",
                    account_id,
                )
            )

    conn.executemany(
        """
        INSERT INTO transactions (
            txn_id, posted_date, amount_cents, merchant_raw, description, currency, account_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(txn_id) DO UPDATE SET
            posted_date = excluded.posted_date,
            amount_cents = excluded.amount_cents,
            merchant_raw = excluded.merchant_raw,
            description = excluded.description,
            currency = excluded.currency,
            account_id = excluded.account_id,
            updated_at = datetime('now')
        """,
        rows,
    )
    conn.commit()
    return len(rows)
