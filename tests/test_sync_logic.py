import unittest
from types import SimpleNamespace

from amazon_spending.api import _should_retry_headed, _sync_completion_note


class SyncLogicTests(unittest.TestCase):
    def test_retry_headed_on_auth_required(self) -> None:
        result = SimpleNamespace(status="auth_required", orders_collected=0, discovered_orders=0)
        self.assertTrue(_should_retry_headed(result))

    def test_retry_headed_on_empty_headless_scrape(self) -> None:
        result = SimpleNamespace(status="no_data", orders_collected=0, discovered_orders=0)
        self.assertTrue(_should_retry_headed(result))

    def test_do_not_retry_headed_when_orders_were_discovered(self) -> None:
        result = SimpleNamespace(status="no_data", orders_collected=0, discovered_orders=4)
        self.assertFalse(_should_retry_headed(result))

    def test_completion_note_with_results(self) -> None:
        note = _sync_completion_note("2026-02-20", 3, 5)
        self.assertEqual(note, "Import complete. Found 3 order(s) since 2026-02-20 and added 5 new transaction(s).")

    def test_completion_note_with_no_changes(self) -> None:
        note = _sync_completion_note("2026-02-20", 0, 0)
        self.assertEqual(note, "No new orders found since 2026-02-20.")


if __name__ == "__main__":
    unittest.main()
