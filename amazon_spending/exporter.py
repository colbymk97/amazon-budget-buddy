from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def _write_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])


def export_reports(conn: sqlite3.Connection, outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)

    itemized = conn.execute(
        """
        SELECT
            t.txn_id,
            t.posted_date,
            t.amount_cents AS txn_amount_cents,
            t.merchant_raw,
            m.order_id,
            m.shipment_id,
            m.item_id,
            oi.title AS item_title,
            m.allocated_amount_cents,
            oi.essential_flag,
            m.confidence,
            m.method
        FROM matches m
        JOIN transactions t ON t.txn_id = m.txn_id
        LEFT JOIN order_items oi ON oi.item_id = m.item_id
        ORDER BY t.posted_date, t.txn_id, m.match_id
        """
    ).fetchall()

    unmatched = conn.execute(
        """
        SELECT t.*
        FROM transactions t
        WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.txn_id = t.txn_id)
        ORDER BY posted_date, txn_id
        """
    ).fetchall()

    monthly = conn.execute(
        """
        SELECT
            substr(t.posted_date, 1, 7) AS month,
            COALESCE(oi.essential_flag, -1) AS essential_flag,
            SUM(m.allocated_amount_cents) AS amount_cents,
            COUNT(DISTINCT t.txn_id) AS txn_count
        FROM matches m
        JOIN transactions t ON t.txn_id = m.txn_id
        LEFT JOIN order_items oi ON oi.item_id = m.item_id
        GROUP BY substr(t.posted_date, 1, 7), COALESCE(oi.essential_flag, -1)
        ORDER BY month, essential_flag
        """
    ).fetchall()

    outputs = {
        "itemized": outdir / "report_transaction_itemized.csv",
        "unmatched": outdir / "report_unmatched.csv",
        "monthly": outdir / "report_monthly_summary.csv",
    }

    _write_csv(outputs["itemized"], itemized)
    _write_csv(outputs["unmatched"], unmatched)
    _write_csv(outputs["monthly"], monthly)
    return outputs
