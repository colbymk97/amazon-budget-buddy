from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar


@dataclass
class CollectResult:
    status: str
    notes: str
    orders_collected: int = 0
    items_collected: int = 0
    orders_inserted: int = 0
    orders_updated: int = 0
    orders_unchanged: int = 0
    shipments_inserted: int = 0
    shipments_updated: int = 0
    shipments_unchanged: int = 0
    items_inserted: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_deleted: int = 0
    amazon_txns_inserted: int = 0
    amazon_txns_updated: int = 0
    amazon_txns_unchanged: int = 0
    amazon_txns_deleted: int = 0
    item_txn_links_written: int = 0
    listing_pages_scanned: int = 0
    discovered_orders: int = 0
    known_orders_matched: int = 0


@dataclass
class ParsedOrder:
    order_id: str
    order_date: str
    order_url: str | None
    order_total_cents: int
    tax_cents: int | None
    shipping_cents: int | None
    payment_last4: str | None


@dataclass
class ParsedItem:
    item_id: str
    order_id: str
    title: str
    quantity: int
    item_subtotal_cents: int


@dataclass
class ParsedRetailerTransaction:
    """A payment transaction scraped from a retailer order page."""
    retailer_txn_id: str
    retailer: str
    order_id: str
    transaction_tag: str | None
    txn_date: str | None
    amount_cents: int | None
    payment_last4: str | None
    raw_label: str | None
    source_url: str | None


class RetailerCollector(ABC):
    """Abstract base for retailer-specific order scrapers.

    Subclasses must set RETAILER_ID (a short lowercase slug, e.g. "amazon")
    and implement collect().
    """

    RETAILER_ID: ClassVar[str]

    @abstractmethod
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
        """Scrape orders for this retailer and reconcile into the DB.

        Args:
            conn: Open SQLite connection (schema already initialized).
            output_dir: Directory to write raw HTML snapshots.
            start_date: ISO date lower bound (inclusive).
            end_date: ISO date upper bound (inclusive).
            order_limit: Max orders to collect in this run.
            max_pages: Max listing pages to traverse.
            headless: Run browser headless (subclass may ignore for non-browser scrapers).
            user_data_dir: Persistent browser profile path.
            test_run: Skip browser launch; parse saved HTML instead.
            saved_run_dir: Specific snapshot dir to parse (implies test_run).
            allow_interactive_auth: Allow prompting for login in headed mode.
            should_abort: Callable polled each iteration; return True to stop early.
            stop_when_before_start_date: Stop when listing pages reach orders older
                than start_date.
            known_order_ids: Recently seen order IDs; used for incremental stop logic.
            overlap_match_threshold: Minimum known-ID hits before stopping scan.

        Returns:
            CollectResult with counts of collected and reconciled records.
        """
        ...
