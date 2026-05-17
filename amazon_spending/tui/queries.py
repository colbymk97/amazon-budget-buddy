"""Read-only DB queries used by the TUI screens.

Each helper opens its own connection so screens can be refreshed independently
without sharing connection state. Queries mirror the shapes the deleted
FastAPI handlers produced.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..db import connect, summarize_retailer_status


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@dataclass
class RetailerOverview:
    retailer: str
    orders: int
    transactions: int
    first_order_date: str | None
    latest_order_date: str | None
    last_import_finished_at: str | None
    last_import_status: str | None
    bound_account: str | None


def dashboard_overview(db_path: Path) -> list[RetailerOverview]:
    conn = connect(db_path)
    try:
        summaries = summarize_retailer_status(conn)
    finally:
        conn.close()
    return [
        RetailerOverview(
            retailer=s.retailer,
            orders=s.order_count,
            transactions=s.transaction_count,
            first_order_date=s.first_order_date,
            latest_order_date=s.latest_order_date,
            last_import_finished_at=s.last_import_finished_at,
            last_import_status=s.last_import_status,
            bound_account=s.bound_account_label,
        )
        for s in summaries
    ]


# ---------------------------------------------------------------------------
# Orders / transactions / items
# ---------------------------------------------------------------------------

def _rows(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_orders(
    db_path: Path,
    *,
    search: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    like = f"%{search.strip()}%"
    start = start_date or "2000-01-01"
    end = end_date or "2100-01-01"
    conn = connect(db_path)
    try:
        return _rows(
            conn,
            """
            SELECT
                o.order_id,
                o.order_date,
                o.order_total_cents,
                o.tax_cents,
                o.shipping_cents,
                o.payment_last4,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT rt.retailer_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN retailer_transactions rt ON rt.order_id = o.order_id
            WHERE o.order_date >= ? AND o.order_date <= ?
              AND (
                o.order_id LIKE ?
                OR EXISTS (
                    SELECT 1 FROM order_items oi2
                    WHERE oi2.order_id = o.order_id AND oi2.title LIKE ?
                )
              )
            GROUP BY o.order_id
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT ?
            """,
            (start, end, like, like, limit),
        )
    finally:
        conn.close()


def list_transactions(
    db_path: Path,
    *,
    search: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    like = f"%{search.strip()}%"
    start = start_date or "2000-01-01"
    end = end_date or "2100-01-01"
    conn = connect(db_path)
    try:
        return _rows(
            conn,
            """
            SELECT
                rt.retailer_txn_id,
                rt.order_id,
                rt.txn_date,
                rt.amount_cents,
                rt.payment_last4,
                rt.raw_label,
                o.order_date
            FROM retailer_transactions rt
            LEFT JOIN orders o ON o.order_id = rt.order_id
            WHERE COALESCE(rt.txn_date, o.order_date, '0000-00-00') >= ?
              AND COALESCE(rt.txn_date, o.order_date, '9999-12-31') <= ?
              AND (
                rt.retailer_txn_id LIKE ?
                OR rt.order_id LIKE ?
                OR COALESCE(rt.raw_label, '') LIKE ?
              )
            ORDER BY COALESCE(rt.txn_date, o.order_date, '0000-00-00') DESC,
                     rt.retailer_txn_id DESC
            LIMIT ?
            """,
            (start, end, like, like, like, limit),
        )
    finally:
        conn.close()


def list_items(
    db_path: Path,
    *,
    search: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    like = f"%{search.strip()}%"
    start = start_date or "2000-01-01"
    end = end_date or "2100-01-01"
    conn = connect(db_path)
    try:
        return _rows(
            conn,
            """
            SELECT
                oi.item_id,
                oi.order_id,
                o.order_date,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents
            FROM order_items oi
            LEFT JOIN orders o ON o.order_id = oi.order_id
            WHERE COALESCE(o.order_date, '0000-00-00') >= ?
              AND COALESCE(o.order_date, '9999-12-31') <= ?
              AND (
                oi.item_id LIKE ?
                OR oi.order_id LIKE ?
                OR COALESCE(oi.title, '') LIKE ?
              )
            ORDER BY COALESCE(o.order_date, '0000-00-00') DESC, oi.order_id DESC
            LIMIT ?
            """,
            (start, end, like, like, like, limit),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Order detail (modal)
# ---------------------------------------------------------------------------

def order_detail(db_path: Path, order_id: str) -> dict[str, Any] | None:
    conn = connect(db_path)
    try:
        order_row = conn.execute(
            """
            SELECT order_id, order_date, order_total_cents, tax_cents,
                   shipping_cents, payment_last4
            FROM orders WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if not order_row:
            return None
        items = _rows(
            conn,
            "SELECT item_id, title, quantity, item_subtotal_cents FROM order_items "
            "WHERE order_id = ? ORDER BY item_id",
            (order_id,),
        )
        txns = _rows(
            conn,
            "SELECT retailer_txn_id, txn_date, amount_cents, raw_label "
            "FROM retailer_transactions WHERE order_id = ? "
            "ORDER BY COALESCE(txn_date, '0000-00-00') DESC",
            (order_id,),
        )
        return {"order": dict(order_row), "items": items, "transactions": txns}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Monthly report
# ---------------------------------------------------------------------------

@dataclass
class MonthlySummary:
    month: str  # YYYY-MM
    net_spend_cents: int
    gross_order_total_cents: int
    order_count: int
    transaction_count: int
    item_count: int


def monthly_summary(db_path: Path, month: str) -> MonthlySummary:
    """Compute totals for orders/transactions/items dated within `month` (YYYY-MM)."""
    start = f"{month}-01"
    # Last day of month: take first day of next month, subtract a day.
    year, mo = int(month[:4]), int(month[5:7])
    if mo == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mo + 1, 1)
    end = (next_first.toordinal() - 1)
    end_date = date.fromordinal(end).isoformat()

    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(o.order_total_cents), 0) AS gross,
                COUNT(*) AS n_orders
            FROM orders o
            WHERE o.order_date BETWEEN ? AND ?
            """,
            (start, end_date),
        ).fetchone()
        gross = row["gross"]
        n_orders = row["n_orders"]

        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(rt.amount_cents), 0) AS net,
                COUNT(*) AS n_txns
            FROM retailer_transactions rt
            LEFT JOIN orders o ON o.order_id = rt.order_id
            WHERE COALESCE(rt.txn_date, o.order_date) BETWEEN ? AND ?
            """,
            (start, end_date),
        ).fetchone()
        net = row["net"]
        n_txns = row["n_txns"]

        row = conn.execute(
            """
            SELECT COUNT(*) AS n_items
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.order_date BETWEEN ? AND ?
            """,
            (start, end_date),
        ).fetchone()
        n_items = row["n_items"]
    finally:
        conn.close()

    return MonthlySummary(
        month=month,
        net_spend_cents=net,
        gross_order_total_cents=gross,
        order_count=n_orders,
        transaction_count=n_txns,
        item_count=n_items,
    )


def top_orders_for_month(db_path: Path, month: str, limit: int = 30) -> list[dict[str, Any]]:
    start = f"{month}-01"
    year, mo = int(month[:4]), int(month[5:7])
    if mo == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, mo + 1, 1)
    end_date = date.fromordinal(next_first.toordinal() - 1).isoformat()

    conn = connect(db_path)
    try:
        return _rows(
            conn,
            """
            SELECT
                o.order_id,
                o.order_date,
                o.order_total_cents,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT rt.retailer_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN retailer_transactions rt ON rt.order_id = o.order_id
            WHERE o.order_date BETWEEN ? AND ?
            GROUP BY o.order_id
            ORDER BY o.order_total_cents DESC
            LIMIT ?
            """,
            (start, end_date, limit),
        )
    finally:
        conn.close()


def available_months(db_path: Path) -> list[str]:
    """All YYYY-MM month buckets present in `orders.order_date`, most recent first."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT substr(order_date, 1, 7) AS m FROM orders "
            "WHERE order_date IS NOT NULL ORDER BY m DESC"
        ).fetchall()
        return [r["m"] for r in rows]
    finally:
        conn.close()
