import unittest

from amazon_spending.db import (
    RetailerAccountMismatchError,
    connect,
    db_status_payload,
    ensure_retailer_account,
    init_db,
    record_retailer_import_run,
)


class DbStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_account_binding_rejects_mismatched_account(self) -> None:
        ensure_retailer_account(self.conn, "amazon", "Colby")

        with self.assertRaises(RetailerAccountMismatchError):
            ensure_retailer_account(self.conn, "amazon", "Different User")

    def test_status_payload_includes_counts_account_and_last_import(self) -> None:
        ensure_retailer_account(self.conn, "amazon", "Colby")
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id, retailer, order_date, order_total_cents
            ) VALUES (?, ?, ?, ?)
            """,
            ("ORDER-1", "amazon", "2026-03-01", 1234),
        )
        self.conn.execute(
            """
            INSERT INTO retailer_transactions (
                retailer_txn_id, retailer, order_id, amount_cents
            ) VALUES (?, ?, ?, ?)
            """,
            ("TX-1", "amazon", "ORDER-1", 1234),
        )
        self.conn.commit()
        record_retailer_import_run(self.conn, "amazon", "ok", "Imported latest orders", account_label="Colby")

        payload = db_status_payload(self.conn)

        self.assertEqual(
            payload,
            {
                "retailers": [
                    {
                        "retailer": "amazon",
                        "orders": 1,
                        "transactions": 1,
                        "last_import_finished_at": payload["retailers"][0]["last_import_finished_at"],
                        "last_import_status": "ok",
                        "bound_account": "Colby",
                    }
                ]
            },
        )
        self.assertIsNotNone(payload["retailers"][0]["last_import_finished_at"])


if __name__ == "__main__":
    unittest.main()
