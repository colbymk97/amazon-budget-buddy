"""Push unsynced retailer transactions to an Actual Budget instance.

Requires the optional ``actualpy`` package::

    pip install actualpy
    # or: pip install "budget-buddy[actual]"

Configuration
-------------
Store Actual Budget settings in the local SQLite database via the CLI::

    budget-buddy actual-configure --base-url http://localhost:5006 --file "My Budget"

The CLI prompts for the password if it is not supplied on the command line.
``account_name`` is optional. When set, transaction matching is restricted to
that Actual account; when omitted all accounts are searched.

How matching works
------------------
For each retailer transaction that has not yet been synced:

1.  Its ``amount_cents`` (already negative for purchases, e.g. -4299 for $42.99)
    is compared directly against ``t.amount`` from actualpy, which uses the same
    cent scale.
2.  Actual transactions within ±3 days of the retailer ``txn_date`` that
    carry the exact milliunit amount are fetched.
3.  The first match has its ``notes`` field updated with the Amazon order ID
    and the line-items that were allocated to that transaction.
4.  ``retailer_transactions.actual_synced_at`` is set to the current UTC
    timestamp so the transaction is never re-synced.

Rows that clearly do not represent imported bank or card activity are marked
with ``actual_skipped_at`` and ``actual_skip_reason`` so future runs focus on
real ledger-backed transactions.

Categories
----------
Budget Buddy never invents its own category taxonomy. ``budget_categories``/
``budget_subcategories`` are a local read-only mirror of Actual's own category
groups/categories, refreshed via ``sync_categories_from_actual()``. If a
transaction has a locally-assigned category *before* its first sync, that
category is pushed to Actual exactly once, at the moment the transaction is
first synced — never again after that, so manual corrections made directly in
Actual are never overwritten. On every sync, the current category is also read
back from Actual into the local mirror, so Budget Buddy's own reports stay
accurate even after you re-categorize something in Actual's UI.

Set ``dry_run=True`` to preview matches without writing anything.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ActualConfig:
    base_url: str
    password: str
    file: str
    account_name: str | None = None


def load_config(conn: sqlite3.Connection) -> ActualConfig | None:
    """Load Actual Budget settings from the local SQLite database."""
    row = conn.execute(
        """
        SELECT base_url, password, file, account_name
        FROM actual_budget_config
        WHERE singleton_id = 1
        """
    ).fetchone()
    if not row:
        return None
    return ActualConfig(
        base_url=row["base_url"],
        password=row["password"],
        file=row["file"],
        account_name=row["account_name"] or None,
    )


def save_config(conn: sqlite3.Connection, config: ActualConfig) -> None:
    conn.execute(
        """
        INSERT INTO actual_budget_config (
            singleton_id, base_url, password, file, account_name, created_at, updated_at
        )
        VALUES (1, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(singleton_id) DO UPDATE SET
            base_url = excluded.base_url,
            password = excluded.password,
            file = excluded.file,
            account_name = excluded.account_name,
            updated_at = datetime('now')
        """,
        (config.base_url, config.password, config.file, config.account_name),
    )
    conn.commit()


def sync_categories_from_actual(db_conn: sqlite3.Connection, config: ActualConfig) -> int:
    """Pull category groups/categories from Actual into the local read-only mirror.

    This only ever reads from Actual — it never creates or edits categories
    there, and never touches per-transaction category assignments. Safe to
    call anytime. Hidden groups/categories in Actual are not imported, since a
    hidden category is a signal the user doesn't want it offered for use.

    Returns the number of categories upserted.
    """
    try:
        from actual import Actual
        from actual.queries import get_categories, get_category_groups
    except ImportError as exc:
        raise RuntimeError(
            "actualpy is not installed. Run: pip install actualpy"
            " (or: pip install \"budget-buddy[actual]\")"
        ) from exc

    with Actual(base_url=config.base_url, password=config.password, file=config.file) as actual:
        groups = get_category_groups(actual.session, include_deleted=False)
        categories = get_categories(actual.session, include_deleted=False)

        for group in groups:
            if group.hidden:
                continue
            db_conn.execute(
                """
                INSERT INTO budget_categories (actual_group_id, name)
                VALUES (?, ?)
                ON CONFLICT(actual_group_id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = datetime('now')
                """,
                (group.id, group.name),
            )
        db_conn.commit()

        group_id_map = {
            row["actual_group_id"]: row["category_id"]
            for row in db_conn.execute(
                "SELECT category_id, actual_group_id FROM budget_categories WHERE actual_group_id IS NOT NULL"
            ).fetchall()
        }

        count = 0
        for category in categories:
            if category.hidden:
                continue
            local_category_id = group_id_map.get(category.cat_group)
            if local_category_id is None:
                continue
            db_conn.execute(
                """
                INSERT INTO budget_subcategories (category_id, actual_category_id, name)
                VALUES (?, ?, ?)
                ON CONFLICT(actual_category_id) DO UPDATE SET
                    category_id = excluded.category_id,
                    name = excluded.name,
                    updated_at = datetime('now')
                """,
                (local_category_id, category.id, category.name),
            )
            count += 1
        db_conn.commit()

    return count


def test_connection(config: ActualConfig) -> None:
    """Validate Actual Budget connectivity and selected budget/account access."""
    try:
        from actual import Actual
        from actual.queries import get_transactions
    except ImportError as exc:
        raise RuntimeError(
            "actualpy is not installed. Run: pip install actualpy"
            " (or: pip install \"budget-buddy[actual]\")"
        ) from exc

    try:
        with Actual(
            base_url=config.base_url,
            password=config.password,
            file=config.file,
        ) as actual:
            if config.account_name:
                today = date.today()
                # A narrow no-op query validates that the configured account filter resolves.
                get_transactions(
                    actual.session,
                    start_date=today,
                    end_date=today + timedelta(days=1),
                    account=config.account_name,
                )
    except Exception as exc:
        raise RuntimeError(f"Actual Budget connection test failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Note builder
# ---------------------------------------------------------------------------

def _build_note(order_id: str, items: list) -> str:
    """Return a multi-line note for one retailer transaction.

    Format::

        Amazon Order: 112-3456789-0123456
        • 1x Some Product Name ($15.99)
        • 2x Another Product ($12.50 each)
    """
    lines = [f"Amazon Order: {order_id}"]
    for item in items:
        qty = item["quantity"]
        title = item["title"]
        alloc = item["allocated_amount_cents"]
        if alloc:
            lines.append(f"• {qty}x {title} (${alloc / 100:.2f})")
        else:
            lines.append(f"• {qty}x {title}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@dataclass
class SyncedRow:
    retailer_txn_id: str
    order_id: str
    txn_date: str
    amount_cents: int


@dataclass
class MissedRow:
    retailer_txn_id: str
    order_id: str
    txn_date: str
    amount_cents: int


@dataclass
class SkippedRow:
    retailer_txn_id: str
    order_id: str
    txn_date: str
    amount_cents: int
    reason: str


@dataclass
class RefreshedRow:
    retailer_txn_id: str
    order_id: str
    txn_date: str
    amount_cents: int


@dataclass
class SyncResult:
    synced: int = 0
    refreshed: int = 0
    skipped: int = 0
    no_match: int = 0
    errors: list[str] = field(default_factory=list)
    synced_rows: list[SyncedRow] = field(default_factory=list)
    refreshed_rows: list[RefreshedRow] = field(default_factory=list)
    skipped_rows: list[SkippedRow] = field(default_factory=list)
    missed_rows: list[MissedRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "synced": self.synced,
            "refreshed": self.refreshed,
            "skipped": self.skipped,
            "no_match": self.no_match,
            "errors": self.errors,
            "synced_rows": [
                {"retailer_txn_id": r.retailer_txn_id, "order_id": r.order_id,
                 "txn_date": r.txn_date, "amount_cents": r.amount_cents}
                for r in self.synced_rows
            ],
            "refreshed_rows": [
                {
                    "retailer_txn_id": r.retailer_txn_id,
                    "order_id": r.order_id,
                    "txn_date": r.txn_date,
                    "amount_cents": r.amount_cents,
                }
                for r in self.refreshed_rows
            ],
            "skipped_rows": [
                {
                    "retailer_txn_id": r.retailer_txn_id,
                    "order_id": r.order_id,
                    "txn_date": r.txn_date,
                    "amount_cents": r.amount_cents,
                    "reason": r.reason,
                }
                for r in self.skipped_rows
            ],
            "missed_rows": [
                {"retailer_txn_id": r.retailer_txn_id, "order_id": r.order_id,
                 "txn_date": r.txn_date, "amount_cents": r.amount_cents}
                for r in self.missed_rows
            ],
        }


def _skip_reason(row: sqlite3.Row) -> str | None:
    raw_label = (row["raw_label"] or "").strip().lower()
    payment_last4 = (row["payment_last4"] or "").strip()
    transaction_tag = (row["transaction_tag"] or "").strip()

    if raw_label.startswith("fallback_"):
        return "synthetic fallback row"
    if raw_label == "amazon gift card":
        return "gift card funded order"
    if raw_label == "amazon visa points":
        return "points-funded offset"
    if raw_label == "order" and not payment_last4 and not transaction_tag:
        return "summary order row without payment metadata"
    return None


def _merge_note(existing: str | None, amazon_block: str) -> str:
    existing_text = (existing or "").strip()
    if not existing_text:
        return amazon_block

    marker = "Amazon Order:"
    if marker not in existing_text:
        return f"{existing_text}\n{amazon_block}".strip()

    prefix, _, _ = existing_text.partition(marker)
    prefix = prefix.rstrip()
    if not prefix:
        return amazon_block
    return f"{prefix}\n{amazon_block}".strip()


def sync_to_actual(
    db_conn: sqlite3.Connection,
    config: ActualConfig,
    dry_run: bool = False,
    refresh_notes: bool = False,
) -> SyncResult:
    """Sync unsynced retailer transactions to Actual Budget.

    Parameters
    ----------
    db_conn:
        Open connection to the local budget-buddy SQLite database.
    config:
        Actual Budget connection settings.
    dry_run:
        When ``True``, matches are found and counted but nothing is written to
        either the Actual Budget server or the local database.

    Returns
    -------
    SyncResult
        Counts of synced transactions, unmatched transactions, and any per-row
        error messages.
    """
    try:
        from actual import Actual
        from actual.queries import get_transactions
    except ImportError as exc:
        raise RuntimeError(
            "actualpy is not installed. Run: pip install actualpy"
            " (or: pip install \"budget-buddy[actual]\")"
        ) from exc

    where_clause = """
        actual_skipped_at IS NULL
        AND txn_date IS NOT NULL
        AND amount_cents IS NOT NULL
    """
    if not refresh_notes:
        where_clause += "\n        AND actual_synced_at IS NULL"

    pending = db_conn.execute(
        f"""
        SELECT retailer_txn_id, txn_date, amount_cents, order_id, raw_label, payment_last4,
               transaction_tag, actual_synced_at, budget_subcategory_id
        FROM retailer_transactions
        WHERE {where_clause}
        ORDER BY txn_date
        """
    ).fetchall()

    # Local subcategory <-> Actual category id maps, used to push a category on
    # first sync and to read the current Actual category back into our mirror.
    subcategory_rows = db_conn.execute(
        "SELECT subcategory_id, category_id, actual_category_id FROM budget_subcategories "
        "WHERE actual_category_id IS NOT NULL"
    ).fetchall()
    local_to_actual_category = {r["subcategory_id"]: r["actual_category_id"] for r in subcategory_rows}
    actual_to_local_category = {
        r["actual_category_id"]: (r["subcategory_id"], r["category_id"]) for r in subcategory_rows
    }

    result = SyncResult()
    synced_ids: list[str] = []
    skipped_updates: list[tuple[str, str]] = []
    category_read_back_updates: list[tuple[int, int, str]] = []
    note_updates_needed = False

    with Actual(
        base_url=config.base_url,
        password=config.password,
        file=config.file,
    ) as actual:
        for row in pending:
            txn_id: str = row["retailer_txn_id"]
            order_id: str = row["order_id"]
            amount_cents: int = row["amount_cents"]

            try:
                txn_date = date.fromisoformat(row["txn_date"])
            except (ValueError, TypeError):
                result.errors.append(f"{txn_id}: invalid date {row['txn_date']!r}")
                continue

            skip_reason = _skip_reason(row)
            if skip_reason:
                result.skipped += 1
                result.skipped_rows.append(
                    SkippedRow(
                        retailer_txn_id=txn_id,
                        order_id=order_id,
                        txn_date=str(txn_date),
                        amount_cents=amount_cents,
                        reason=skip_reason,
                    )
                )
                if not dry_run:
                    skipped_updates.append((skip_reason, txn_id))
                continue

            # Load items allocated to this transaction (may be empty if
            # run before the `match` step).
            items = db_conn.execute(
                """
                SELECT oi.title, oi.quantity, oit.allocated_amount_cents
                FROM order_item_transactions oit
                JOIN order_items oi ON oi.item_id = oit.item_id
                WHERE oit.retailer_txn_id = ?
                ORDER BY oit.allocated_amount_cents DESC
                """,
                (txn_id,),
            ).fetchall()

            note = _build_note(order_id, items)

            # retailer_transactions.amount_cents is already negative for purchases
            # (e.g. -4299 for a $42.99 charge). actualpy returns t.amount in the
            # same cent scale, so compare directly.
            actual_amount = amount_cents

            window_start = txn_date - timedelta(days=3)
            window_end = txn_date + timedelta(days=3)

            try:
                # end_date is exclusive in actualpy
                candidates = get_transactions(
                    actual.session,
                    start_date=window_start,
                    end_date=window_end + timedelta(days=1),
                    account=config.account_name,
                )
                matches = [
                    t for t in candidates
                    if t.amount == actual_amount and not t.is_parent
                ]
            except Exception as exc:
                result.errors.append(f"{txn_id}: query error — {exc}")
                continue

            if not matches:
                result.no_match += 1
                result.missed_rows.append(MissedRow(
                    retailer_txn_id=txn_id,
                    order_id=order_id,
                    txn_date=str(txn_date),
                    amount_cents=amount_cents,
                ))
                continue

            order_matches = [
                t for t in matches
                if order_id in ((t.notes or ""))
            ]
            best = order_matches[0] if order_matches else matches[0]

            # Write-once category push: only at the NULL -> synced transition, and
            # only if Actual doesn't already have a category — never override a
            # choice made directly in Actual, and never revisit on later syncs.
            if (
                not dry_run
                and row["actual_synced_at"] is None
                and best.category_id is None
                and row["budget_subcategory_id"] is not None
            ):
                actual_category_id = local_to_actual_category.get(row["budget_subcategory_id"])
                if actual_category_id is not None:
                    best.category_id = actual_category_id
                    note_updates_needed = True

            # Read-back: keep our local category mirror in sync with whatever
            # Actual currently has. This only reads from Actual, never writes to
            # it, so it's safe to do on every matched row regardless of sync state.
            if best.category_id is not None:
                mapped = actual_to_local_category.get(best.category_id)
                if mapped is not None:
                    local_subcategory_id, local_category_id = mapped
                    if local_subcategory_id != row["budget_subcategory_id"]:
                        category_read_back_updates.append((local_category_id, local_subcategory_id, txn_id))

            existing_note = (best.notes or "").strip()
            merged_note = _merge_note(best.notes, note)
            note_changed = merged_note != existing_note

            if not dry_run:
                if note_changed:
                    best.notes = merged_note
                    note_updates_needed = True
            if row["actual_synced_at"] is None:
                synced_ids.append(txn_id)
            elif note_changed:
                result.refreshed += 1
                result.refreshed_rows.append(RefreshedRow(
                    retailer_txn_id=txn_id,
                    order_id=order_id,
                    txn_date=str(txn_date),
                    amount_cents=amount_cents,
                ))

            if row["actual_synced_at"] is None:
                result.synced += 1
                result.synced_rows.append(SyncedRow(
                    retailer_txn_id=txn_id,
                    order_id=order_id,
                    txn_date=str(txn_date),
                    amount_cents=amount_cents,
                ))

        if not dry_run and note_updates_needed:
            actual.commit()

    if not dry_run and synced_ids:
        db_conn.executemany(
            """
            UPDATE retailer_transactions
            SET actual_synced_at = datetime('now')
            WHERE retailer_txn_id = ?
            """,
            [(txn_id,) for txn_id in synced_ids],
        )
        db_conn.commit()

    if not dry_run and skipped_updates:
        db_conn.executemany(
            """
            UPDATE retailer_transactions
            SET actual_skipped_at = datetime('now'),
                actual_skip_reason = ?
            WHERE retailer_txn_id = ?
            """,
            skipped_updates,
        )
        db_conn.commit()

    if not dry_run and category_read_back_updates:
        db_conn.executemany(
            """
            UPDATE retailer_transactions
            SET budget_category_id = ?,
                budget_subcategory_id = ?
            WHERE retailer_txn_id = ?
            """,
            category_read_back_updates,
        )
        db_conn.commit()

    return result
