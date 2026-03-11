import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

from amazon_spending.cli import _handle_collect
from amazon_spending.db import connect, init_db
from amazon_spending.retailers.amazon import (
    ListingOrderSummary,
    _build_collect_result,
    _extract_listing_order_summaries_from_html,
    _merge_listing_orders,
    _should_skip_detail_fetch,
)
from amazon_spending.retailers.base import CollectResult, ParsedItem, ParsedOrder, ParsedRetailerTransaction


class _FakeCollector:
    def __init__(self) -> None:
        self.kwargs = None

    def collect(self, **kwargs):
        self.kwargs = kwargs
        return CollectResult(status="ok", notes="ok")


class AmazonCollectLogicTests(unittest.TestCase):
    def _sample_collect_payload(
        self,
        *,
        order_total_cents: int = 2500,
        item_subtotal_cents: int = 2500,
        txn_amount_cents: int = 2500,
        raw_label: str = "Visa ending in 4242",
    ):
        order = ParsedOrder(
            order_id="111-1111111-1111111",
            order_date="2026-02-28",
            order_url="https://example.test/orders/111",
            order_total_cents=order_total_cents,
            tax_cents=200,
            shipping_cents=0,
            payment_last4="4242",
        )
        item = ParsedItem(
            item_id=f"{order.order_id}-I1",
            order_id=order.order_id,
            title="Test item",
            quantity=1,
            item_subtotal_cents=item_subtotal_cents,
        )
        txn = ParsedRetailerTransaction(
            retailer_txn_id=f"{order.order_id}-TX-1",
            retailer="amazon",
            order_id=order.order_id,
            transaction_tag=order.order_id,
            txn_date=order.order_date,
            amount_cents=txn_amount_cents,
            payment_last4="4242",
            raw_label=raw_label,
            source_url="https://example.test/tx/111",
        )
        return order, item, txn

    def test_extract_listing_order_summaries_preserves_dates(self) -> None:
        html = """
        <div class="order-card">
          <span>ORDER PLACED</span><span>February 28, 2026</span>
          <a href="/gp/your-account/order-details?orderID=111-1111111-1111111">Order details</a>
        </div>
        <div class="order-card">
          <span>ORDER PLACED</span><span>February 10, 2026</span>
          <a href="/gp/your-account/order-details?orderID=222-2222222-2222222">Order details</a>
        </div>
        """

        summaries = _extract_listing_order_summaries_from_html(html)

        self.assertEqual(
            summaries,
            [
                ListingOrderSummary("111-1111111-1111111", "2026-02-28"),
                ListingOrderSummary("222-2222222-2222222", "2026-02-10"),
            ],
        )

    def test_merge_listing_orders_stops_at_first_known_order(self) -> None:
        current_orders = [
            ListingOrderSummary("111-1111111-1111111", "2026-02-28"),
            ListingOrderSummary("222-2222222-2222222", "2026-02-20"),
            ListingOrderSummary("333-3333333-3333333", "2026-02-10"),
        ]

        collected, matched_known, stop_after_known = _merge_listing_orders(
            current_orders,
            seen_orders=set(),
            known_order_id_set={"222-2222222-2222222"},
            collected_orders=[],
            order_limit=None,
        )

        self.assertEqual(collected, [ListingOrderSummary("111-1111111-1111111", "2026-02-28")])
        self.assertEqual(matched_known, {"222-2222222-2222222"})
        self.assertTrue(stop_after_known)

    def test_listing_date_can_skip_detail_fetch(self) -> None:
        self.assertTrue(
            _should_skip_detail_fetch(
                ListingOrderSummary("111-1111111-1111111", "2026-01-31"),
                start_date="2026-02-01",
                end_date="2026-02-28",
            )
        )
        self.assertFalse(
            _should_skip_detail_fetch(
                ListingOrderSummary("111-1111111-1111111", "2026-02-15"),
                start_date="2026-02-01",
                end_date="2026-02-28",
            )
        )

    def test_cli_stop_on_known_passes_recent_db_order_ids_to_collector(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        conn.execute(
            """
            INSERT INTO orders (order_id, retailer, order_date, order_total_cents)
            VALUES (?, ?, ?, ?)
            """,
            ("111-1111111-1111111", "amazon", "2026-02-28", 1000),
        )
        conn.commit()

        args = Namespace(
            outdir=None,
            user_data_dir=None,
            test_run=False,
            saved_run_dir=None,
            start_date="2026-02-01",
            end_date="2026-02-28",
            order_limit=None,
            max_pages=None,
            headed=False,
            stop_on_known=True,
            output_json=False,
        )
        fake_collector = _FakeCollector()

        try:
            with patch("amazon_spending.cli.REGISTRY", {"amazon": fake_collector}):
                with redirect_stdout(io.StringIO()):
                    _handle_collect(args, conn, "amazon")
        finally:
            conn.close()

        self.assertEqual(fake_collector.kwargs["known_order_ids"], ["111-1111111-1111111"])

    def test_build_collect_result_inserts_expected_rows_into_sqlite(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        order, item, txn = self._sample_collect_payload()

        try:
            result = _build_collect_result(
                conn,
                [order],
                [item],
                {order.order_id: [txn]},
                {order.order_id: [item]},
                "test run",
            )

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.orders_inserted, 1)
            self.assertEqual(result.shipments_inserted, 1)
            self.assertEqual(result.items_inserted, 1)
            self.assertEqual(result.amazon_txns_inserted, 1)
            self.assertEqual(result.item_txn_links_written, 1)

            order_row = conn.execute(
                "SELECT retailer, order_date, order_total_cents, payment_last4 FROM orders WHERE order_id = ?",
                (order.order_id,),
            ).fetchone()
            shipment_row = conn.execute(
                "SELECT order_id, shipment_total_cents FROM shipments WHERE shipment_id = ?",
                (f'{order.order_id}-S1',),
            ).fetchone()
            item_row = conn.execute(
                "SELECT retailer_transaction_id, item_subtotal_cents FROM order_items WHERE item_id = ?",
                (item.item_id,),
            ).fetchone()
            txn_row = conn.execute(
                "SELECT retailer, amount_cents, txn_date FROM retailer_transactions WHERE retailer_txn_id = ?",
                (txn.retailer_txn_id,),
            ).fetchone()
            link_row = conn.execute(
                "SELECT allocated_amount_cents, method FROM order_item_transactions WHERE item_id = ? AND retailer_txn_id = ?",
                (item.item_id, txn.retailer_txn_id),
            ).fetchone()

            self.assertEqual(dict(order_row), {
                "retailer": "amazon",
                "order_date": "2026-02-28",
                "order_total_cents": 2500,
                "payment_last4": "4242",
            })
            self.assertEqual(dict(shipment_row), {"order_id": order.order_id, "shipment_total_cents": 2500})
            self.assertEqual(dict(item_row), {"retailer_transaction_id": txn.retailer_txn_id, "item_subtotal_cents": 2500})
            self.assertEqual(dict(txn_row), {"retailer": "amazon", "amount_cents": 2500, "txn_date": "2026-02-28"})
            self.assertEqual(dict(link_row), {"allocated_amount_cents": 2500, "method": "single_transaction"})
        finally:
            conn.close()

    def test_build_collect_result_updates_existing_rows_on_second_run(self) -> None:
        conn = connect(":memory:")
        init_db(conn)
        order, item, txn = self._sample_collect_payload()

        try:
            _build_collect_result(
                conn,
                [order],
                [item],
                {order.order_id: [txn]},
                {order.order_id: [item]},
                "initial run",
            )

            updated_order, updated_item, updated_txn = self._sample_collect_payload(
                order_total_cents=3100,
                item_subtotal_cents=3100,
                txn_amount_cents=3100,
                raw_label="Mastercard ending in 9999",
            )
            updated_order.payment_last4 = "9999"
            updated_txn.payment_last4 = "9999"

            result = _build_collect_result(
                conn,
                [updated_order],
                [updated_item],
                {updated_order.order_id: [updated_txn]},
                {updated_order.order_id: [updated_item]},
                "second run",
            )

            self.assertEqual(result.orders_updated, 1)
            self.assertEqual(result.shipments_updated, 1)
            self.assertEqual(result.items_updated, 1)
            self.assertEqual(result.amazon_txns_updated, 1)
            self.assertEqual(result.item_txn_links_written, 1)

            order_row = conn.execute(
                "SELECT order_total_cents, payment_last4 FROM orders WHERE order_id = ?",
                (updated_order.order_id,),
            ).fetchone()
            item_row = conn.execute(
                "SELECT item_subtotal_cents, retailer_transaction_id FROM order_items WHERE item_id = ?",
                (updated_item.item_id,),
            ).fetchone()
            txn_row = conn.execute(
                "SELECT amount_cents, payment_last4, raw_label FROM retailer_transactions WHERE retailer_txn_id = ?",
                (updated_txn.retailer_txn_id,),
            ).fetchone()
            link_row = conn.execute(
                "SELECT allocated_amount_cents, method FROM order_item_transactions WHERE item_id = ? AND retailer_txn_id = ?",
                (updated_item.item_id, updated_txn.retailer_txn_id),
            ).fetchone()

            self.assertEqual(dict(order_row), {"order_total_cents": 3100, "payment_last4": "9999"})
            self.assertEqual(
                dict(item_row),
                {"item_subtotal_cents": 3100, "retailer_transaction_id": updated_txn.retailer_txn_id},
            )
            self.assertEqual(
                dict(txn_row),
                {"amount_cents": 3100, "payment_last4": "9999", "raw_label": "Mastercard ending in 9999"},
            )
            self.assertEqual(dict(link_row), {"allocated_amount_cents": 3100, "method": "single_transaction"})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
