"""Unit tests for the read-only DB helpers powering the TUI screens."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amazon_spending.db import connect, init_db
from amazon_spending.tui.queries import (
    available_months,
    dashboard_overview,
    list_items,
    list_orders,
    list_transactions,
    monthly_summary,
    order_detail,
    top_orders_for_month,
)


class TuiQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        # The TUI queries open their own connections via paths.default_db_path,
        # so we need a real file on disk that they can re-open.
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite3"
        conn = connect(self.db_path)
        try:
            init_db(conn)
            self._seed(conn)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed(self, conn) -> None:
        conn.execute(
            "INSERT INTO orders (order_id, retailer, order_date, order_total_cents, tax_cents, shipping_cents, payment_last4) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ORDER-1", "amazon", "2026-04-15", 5000, 400, 0, "1234"),
        )
        conn.execute(
            "INSERT INTO orders (order_id, retailer, order_date, order_total_cents, tax_cents, shipping_cents, payment_last4) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ORDER-2", "amazon", "2026-04-20", 2500, 200, 0, "1234"),
        )
        conn.execute(
            "INSERT INTO orders (order_id, retailer, order_date, order_total_cents, tax_cents, shipping_cents, payment_last4) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ORDER-3", "amazon", "2026-05-02", 1000, 0, 0, "1234"),
        )

        conn.execute(
            "INSERT INTO order_items (item_id, order_id, title, quantity, item_subtotal_cents) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ORDER-1-I1", "ORDER-1", "Widget A", 1, 5000),
        )
        conn.execute(
            "INSERT INTO order_items (item_id, order_id, title, quantity, item_subtotal_cents) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ORDER-2-I1", "ORDER-2", "Gadget B", 2, 2500),
        )

        conn.execute(
            "INSERT INTO retailer_transactions (retailer_txn_id, retailer, order_id, txn_date, amount_cents, raw_label) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("TX-1", "amazon", "ORDER-1", "2026-04-16", -5400, "Order"),
        )
        conn.execute(
            "INSERT INTO retailer_transactions (retailer_txn_id, retailer, order_id, txn_date, amount_cents, raw_label) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("TX-2", "amazon", "ORDER-2", "2026-04-21", -2700, "Order"),
        )

    def test_dashboard_overview_returns_amazon_row(self) -> None:
        rows = dashboard_overview(self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].retailer, "amazon")
        self.assertEqual(rows[0].orders, 3)
        self.assertEqual(rows[0].transactions, 2)
        self.assertEqual(rows[0].first_order_date, "2026-04-15")
        self.assertEqual(rows[0].latest_order_date, "2026-05-02")

    def test_list_orders_search_filters_by_title(self) -> None:
        rows = list_orders(self.db_path, search="Gadget")
        self.assertEqual([r["order_id"] for r in rows], ["ORDER-2"])

    def test_list_orders_date_range(self) -> None:
        rows = list_orders(self.db_path, start_date="2026-04-01", end_date="2026-04-30")
        self.assertEqual(sorted(r["order_id"] for r in rows), ["ORDER-1", "ORDER-2"])

    def test_list_transactions_orders_recent_first(self) -> None:
        rows = list_transactions(self.db_path)
        self.assertEqual([r["retailer_txn_id"] for r in rows], ["TX-2", "TX-1"])

    def test_list_items_search_filters_by_title(self) -> None:
        rows = list_items(self.db_path, search="Widget")
        self.assertEqual([r["item_id"] for r in rows], ["ORDER-1-I1"])

    def test_order_detail_returns_items_and_transactions(self) -> None:
        detail = order_detail(self.db_path, "ORDER-1")
        assert detail is not None
        self.assertEqual(detail["order"]["order_id"], "ORDER-1")
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(len(detail["transactions"]), 1)

    def test_order_detail_missing_returns_none(self) -> None:
        self.assertIsNone(order_detail(self.db_path, "ORDER-NOPE"))

    def test_monthly_summary_april(self) -> None:
        s = monthly_summary(self.db_path, "2026-04")
        self.assertEqual(s.order_count, 2)
        self.assertEqual(s.transaction_count, 2)
        self.assertEqual(s.item_count, 2)
        self.assertEqual(s.gross_order_total_cents, 7500)
        # Net spend = sum of (negative) txn amounts in window.
        self.assertEqual(s.net_spend_cents, -8100)

    def test_monthly_summary_may_only_counts_may(self) -> None:
        s = monthly_summary(self.db_path, "2026-05")
        self.assertEqual(s.order_count, 1)
        self.assertEqual(s.gross_order_total_cents, 1000)

    def test_top_orders_for_month_orders_by_total_desc(self) -> None:
        rows = top_orders_for_month(self.db_path, "2026-04", limit=10)
        self.assertEqual([r["order_id"] for r in rows], ["ORDER-1", "ORDER-2"])

    def test_available_months_recent_first(self) -> None:
        months = available_months(self.db_path)
        self.assertEqual(months, ["2026-05", "2026-04"])


if __name__ == "__main__":
    unittest.main()
