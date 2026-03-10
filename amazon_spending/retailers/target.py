from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from .base import CollectResult, RetailerCollector


class TargetCollector(RetailerCollector):
    """Retailer adapter for Target order history (not yet implemented).

    To add Target support, implement the collect() method following the
    same interface as AmazonCollector in retailers/amazon.py.
    """

    RETAILER_ID = "target"

    def collect(
        self,
        conn: sqlite3.Connection,
        output_dir: Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        order_limit: int | None = None,
        max_pages: int | None = None,
        headless: bool = True,
        user_data_dir: Path | None = None,
        test_run: bool = False,
        saved_run_dir: Path | None = None,
        allow_interactive_auth: bool = True,
        should_abort: Callable[[], bool] | None = None,
        stop_when_before_start_date: bool = False,
        known_order_ids: list[str] | None = None,
        overlap_match_threshold: int = 1,
    ) -> CollectResult:
        raise NotImplementedError(
            "Target scraping is not yet implemented.\n"
            "To add support, implement TargetCollector.collect() in\n"
            "amazon_spending/retailers/target.py following the RetailerCollector\n"
            "interface defined in amazon_spending/retailers/base.py."
        )
