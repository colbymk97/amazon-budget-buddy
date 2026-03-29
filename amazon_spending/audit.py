"""
Audit commands: compare local DB order data against Amazon's live order listing.

Two modes
---------
full
    Scan Amazon listing pages from today back to the date of the *oldest* order
    stored locally.  Reports every order that appears on Amazon in that window
    but is absent from the local database.
    CLI alias: from-first-transaction

latest
    Scan Amazon listing pages from today until the *most-recent* locally-known
    order is encountered.  Reports orders that appeared after the last collect
    run.
    CLI alias: from-latest-transaction

Only listing pages are fetched — no order detail or payment pages are opened —
so the audit is fast and read-only (nothing is written to the database).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MissingOrder:
    order_id: str
    order_date: str | None


@dataclass
class AuditResult:
    mode: str                             # "full" | "latest"
    anchor_date: str | None               # oldest date (full) or newest date (latest)
    status: str                           # "ok" | "error" | "auth_required" | "no_data"
    notes: str
    pages_scanned: int = 0
    amazon_orders_in_scope: int = 0       # Amazon orders found in the scanned window
    db_orders_in_scope: int = 0           # DB orders in the equivalent date window
    missing_orders: list[MissingOrder] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "anchor_date": self.anchor_date,
            "status": self.status,
            "notes": self.notes,
            "pages_scanned": self.pages_scanned,
            "amazon_orders_in_scope": self.amazon_orders_in_scope,
            "db_orders_in_scope": self.db_orders_in_scope,
            "missing_count": len(self.missing_orders),
            "missing_orders": [
                {"order_id": m.order_id, "order_date": m.order_date}
                for m in self.missing_orders
            ],
        }


# ---------------------------------------------------------------------------
# DB helpers (read-only)
# ---------------------------------------------------------------------------

def _get_oldest_order_date(conn: sqlite3.Connection, retailer: str = "amazon") -> str | None:
    row = conn.execute(
        "SELECT MIN(order_date) FROM orders WHERE retailer = ?", (retailer,)
    ).fetchone()
    return row[0] if row else None


def _get_newest_order_date(conn: sqlite3.Connection, retailer: str = "amazon") -> str | None:
    row = conn.execute(
        "SELECT MAX(order_date) FROM orders WHERE retailer = ?", (retailer,)
    ).fetchone()
    return row[0] if row else None


def _get_all_order_ids(conn: sqlite3.Connection, retailer: str = "amazon") -> set[str]:
    rows = conn.execute(
        "SELECT order_id FROM orders WHERE retailer = ?", (retailer,)
    ).fetchall()
    return {row[0] for row in rows}


def _get_order_count_since(conn: sqlite3.Connection, since_date: str, retailer: str = "amazon") -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE retailer = ? AND order_date >= ?",
        (retailer, since_date),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------

def audit_amazon(
    conn: sqlite3.Connection,
    mode: str,
    output_dir: Path,
    headless: bool = True,
    user_data_dir: Path | None = None,
) -> AuditResult:
    """Audit Amazon order history against the local database.

    Parameters
    ----------
    conn:
        Open connection to the local SQLite database.
    mode:
        ``"full"`` — scan from today back to the oldest locally-known order date.
        ``"latest"`` — scan from today until the most-recent locally-known order
        is encountered on a listing page.
    output_dir:
        Directory that holds the persistent browser profile (same as collect).
        No HTML is saved by this command.
    headless:
        Run browser headless (set False to debug or handle MFA).
    user_data_dir:
        Override the browser profile directory.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return AuditResult(
            mode=mode,
            anchor_date=None,
            status="error",
            notes="Playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    # Lazy import to avoid circular-import issues (audit imports from retailers).
    from .retailers.amazon import (  # type: ignore[attr-defined]
        _extract_listing_order_summaries_from_html,
        _launch_and_open_orders,
        _orders_page_ready,
        _wait_for_orders_page_ready,
        ListingOrderSummary,
    )

    # ------------------------------------------------------------------
    # Determine anchor date and current DB snapshot
    # ------------------------------------------------------------------
    if mode == "full":
        anchor_date = _get_oldest_order_date(conn, "amazon")
        if anchor_date is None:
            return AuditResult(
                mode=mode,
                anchor_date=None,
                status="no_data",
                notes="No orders found in the local database. Run 'collect' first.",
            )
        db_count = len(_get_all_order_ids(conn, "amazon"))
    else:  # "latest"
        anchor_date = _get_newest_order_date(conn, "amazon")
        if anchor_date is None:
            return AuditResult(
                mode=mode,
                anchor_date=None,
                status="no_data",
                notes="No orders found in the local database. Run 'collect' first.",
            )
        db_count = _get_order_count_since(conn, anchor_date, "amazon")

    known_order_ids = _get_all_order_ids(conn, "amazon")

    # ------------------------------------------------------------------
    # Browser: listing-only scrape
    # ------------------------------------------------------------------
    profile_dir = user_data_dir or (output_dir / "browser_profile")
    profile_dir.mkdir(parents=True, exist_ok=True)

    collected: list[ListingOrderSummary] = []
    pages_scanned = 0
    stopped_reason = "exhausted all listing pages"

    with sync_playwright() as p:
        context, page = _launch_and_open_orders(p, profile_dir, headless=headless)

        if not _orders_page_ready(page):
            context.close()
            return AuditResult(
                mode=mode,
                anchor_date=anchor_date,
                status="auth_required",
                notes=(
                    "Amazon session is not authenticated or the orders page did not load. "
                    "Run: amazon-spending login --retailer amazon"
                ),
            )

        seen: set[str] = set()
        consecutive_older = 0
        page_num = 1

        while True:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError:
                pass

            summaries = _extract_listing_order_summaries_from_html(page.content())
            pages_scanned = page_num
            stop = False

            for summary in summaries:
                oid = summary.order_id
                if oid in seen:
                    continue
                seen.add(oid)

                if mode == "latest":
                    # Stop as soon as we hit any order that's already in the DB.
                    if oid in known_order_ids:
                        stopped_reason = f"reached known order {oid}"
                        stop = True
                        break
                    collected.append(summary)
                else:  # full
                    # Collect everything down to anchor_date; stop when we're
                    # consistently past it (3 consecutive older orders = buffer
                    # for any non-chronological edge cases).
                    if summary.order_date and summary.order_date < anchor_date:
                        consecutive_older += 1
                        if consecutive_older >= 3:
                            stopped_reason = f"reached orders older than anchor date {anchor_date}"
                            stop = True
                            break
                    else:
                        consecutive_older = 0
                        collected.append(summary)

            print(
                f"[audit/{mode}] page={page_num} this_page={len(summaries)} "
                f"collected={len(collected)} consecutive_older={consecutive_older}"
            )

            if stop:
                break

            next_link = page.locator("li.a-last a")
            if next_link.count() == 0:
                break

            next_link.first.click()
            page_num += 1

        context.close()

    # ------------------------------------------------------------------
    # Compare against DB
    # ------------------------------------------------------------------
    missing = [
        MissingOrder(order_id=s.order_id, order_date=s.order_date)
        for s in collected
        if s.order_id not in known_order_ids
    ]
    # Sort by date ascending so the report reads oldest-first.
    missing.sort(key=lambda m: (m.order_date or ""))

    notes_parts = [f"Scanned {pages_scanned} listing page(s); {stopped_reason}."]
    if missing:
        notes_parts.append(f"{len(missing)} order(s) found on Amazon that are not in the local database.")
    else:
        notes_parts.append("No missing orders detected.")

    return AuditResult(
        mode=mode,
        anchor_date=anchor_date,
        status="ok",
        notes=" ".join(notes_parts),
        pages_scanned=pages_scanned,
        amazon_orders_in_scope=len(collected),
        db_orders_in_scope=db_count,
        missing_orders=missing,
    )
