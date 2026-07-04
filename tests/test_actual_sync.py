import sys
import types
import unittest

from amazon_spending.actual_sync import ActualConfig, sync_to_actual
from amazon_spending.db import connect, init_db


class _FakeActualTransaction:
    amount = -1250
    is_parent = False
    notes = ""


_FAKE_TRANSACTION = _FakeActualTransaction()


class _FakeActual:
    fail_commit = False
    latest = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.session = object()
        self.committed = False
        _FakeActual.latest = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("actual commit failed")
        self.committed = True


def _fake_get_transactions(*args, **kwargs):
    return [_FAKE_TRANSACTION]


class ActualSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.conn.execute(
            """
            INSERT INTO orders (order_id, retailer, order_date, order_total_cents)
            VALUES (?, ?, ?, ?)
            """,
            ("ORDER-1", "amazon", "2026-03-01", 1250),
        )
        self.conn.execute(
            """
            INSERT INTO retailer_transactions (
                retailer_txn_id, retailer, order_id, txn_date, amount_cents
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("TX-1", "amazon", "ORDER-1", "2026-03-02", -1250),
        )
        self.conn.execute(
            """
            INSERT INTO order_items (
                item_id, order_id, title, quantity, item_subtotal_cents
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("ITEM-1", "ORDER-1", "Example Item", 1, 1250),
        )
        self.conn.execute(
            """
            INSERT INTO order_item_transactions (
                item_id, retailer_txn_id, allocated_amount_cents, method
            ) VALUES (?, ?, ?, ?)
            """,
            ("ITEM-1", "TX-1", 1250, "single_transaction"),
        )
        self.conn.commit()

        _FAKE_TRANSACTION.notes = ""

        self.actual_module = types.ModuleType("actual")
        self.actual_module.Actual = _FakeActual
        self.queries_module = types.ModuleType("actual.queries")
        self.queries_module.get_transactions = _fake_get_transactions
        self.original_actual = sys.modules.get("actual")
        self.original_queries = sys.modules.get("actual.queries")
        sys.modules["actual"] = self.actual_module
        sys.modules["actual.queries"] = self.queries_module

    def tearDown(self) -> None:
        self.conn.close()
        if self.original_actual is None:
            sys.modules.pop("actual", None)
        else:
            sys.modules["actual"] = self.original_actual
        if self.original_queries is None:
            sys.modules.pop("actual.queries", None)
        else:
            sys.modules["actual.queries"] = self.original_queries

    def test_sync_marks_sqlite_only_after_actual_commit_succeeds(self) -> None:
        _FakeActual.fail_commit = False

        result = sync_to_actual(
            self.conn,
            ActualConfig(base_url="http://example.test", password="secret", file="Budget"),
        )

        self.assertEqual(result.synced, 1)
        self.assertTrue(_FakeActual.latest.committed)
        row = self.conn.execute(
            "SELECT actual_synced_at FROM retailer_transactions WHERE retailer_txn_id = ?",
            ("TX-1",),
        ).fetchone()
        self.assertIsNotNone(row["actual_synced_at"])

    def test_sync_does_not_mark_sqlite_when_actual_commit_fails(self) -> None:
        _FakeActual.fail_commit = True

        with self.assertRaises(RuntimeError):
            sync_to_actual(
                self.conn,
                ActualConfig(base_url="http://example.test", password="secret", file="Budget"),
            )

        row = self.conn.execute(
            "SELECT actual_synced_at FROM retailer_transactions WHERE retailer_txn_id = ?",
            ("TX-1",),
        ).fetchone()
        self.assertIsNone(row["actual_synced_at"])

    def test_sync_skips_non_bank_rows_and_marks_skip_reason(self) -> None:
        self.conn.execute(
            """
            UPDATE retailer_transactions
            SET raw_label = ?, payment_last4 = NULL, transaction_tag = NULL
            WHERE retailer_txn_id = ?
            """,
            ("Order", "TX-1"),
        )
        self.conn.commit()

        result = sync_to_actual(
            self.conn,
            ActualConfig(base_url="http://example.test", password="secret", file="Budget"),
        )

        self.assertEqual(result.synced, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.no_match, 0)

        row = self.conn.execute(
            """
            SELECT actual_synced_at, actual_skipped_at, actual_skip_reason
            FROM retailer_transactions
            WHERE retailer_txn_id = ?
            """,
            ("TX-1",),
        ).fetchone()
        self.assertIsNone(row["actual_synced_at"])
        self.assertIsNotNone(row["actual_skipped_at"])
        self.assertEqual(row["actual_skip_reason"], "summary order row without payment metadata")

    def test_refresh_notes_rewrites_existing_amazon_block_with_items(self) -> None:
        self.conn.execute(
            """
            UPDATE retailer_transactions
            SET actual_synced_at = datetime('now')
            WHERE retailer_txn_id = ?
            """,
            ("TX-1",),
        )
        self.conn.commit()
        _FakeActual.fail_commit = False
        _FAKE_TRANSACTION.notes = "Amazon.comAmazon Order: ORDER-1"

        result = sync_to_actual(
            self.conn,
            ActualConfig(base_url="http://example.test", password="secret", file="Budget"),
            refresh_notes=True,
        )

        self.assertEqual(result.synced, 0)
        self.assertEqual(result.refreshed, 1)
        self.assertTrue(_FakeActual.latest.committed)
        self.assertEqual(
            _FAKE_TRANSACTION.notes,
            "Amazon.com\nAmazon Order: ORDER-1\n• 1x Example Item ($12.50)",
        )


if __name__ == "__main__":
    unittest.main()
