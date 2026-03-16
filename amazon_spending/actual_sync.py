"""Push unsynced retailer transactions to an Actual Budget instance.

Requires the optional ``actualpy`` package::

    pip install actualpy
    # or: pip install "amazon-spending[actual]"

Configuration
-------------
Store Actual Budget settings in the local SQLite database via the CLI::

    amazon-spending actual-configure --base-url http://localhost:5006 --file "My Budget"

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


def test_connection(config: ActualConfig) -> None:
    """Validate Actual Budget connectivity and selected budget/account access."""
    try:
        from actual import Actual
        from actual.queries import get_transactions
    except ImportError as exc:
        raise RuntimeError(
            "actualpy is not installed. Run: pip install actualpy"
            " (or: pip install \"amazon-spending[actual]\")"
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
class SyncResult:
    synced: int = 0
    no_match: int = 0
    errors: list[str] = field(default_factory=list)
    synced_rows: list[SyncedRow] = field(default_factory=list)
    missed_rows: list[MissedRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "synced": self.synced,
            "no_match": self.no_match,
            "errors": self.errors,
            "synced_rows": [
                {"retailer_txn_id": r.retailer_txn_id, "order_id": r.order_id,
                 "txn_date": r.txn_date, "amount_cents": r.amount_cents}
                for r in self.synced_rows
            ],
            "missed_rows": [
                {"retailer_txn_id": r.retailer_txn_id, "order_id": r.order_id,
                 "txn_date": r.txn_date, "amount_cents": r.amount_cents}
                for r in self.missed_rows
            ],
        }


def sync_to_actual(
    db_conn: sqlite3.Connection,
    config: ActualConfig,
    dry_run: bool = False,
) -> SyncResult:
    """Sync unsynced retailer transactions to Actual Budget.

    Parameters
    ----------
    db_conn:
        Open connection to the local amazon-spending SQLite database.
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
            " (or: pip install \"amazon-spending[actual]\")"
        ) from exc

    pending = db_conn.execute(
        """
        SELECT retailer_txn_id, txn_date, amount_cents, order_id
        FROM retailer_transactions
        WHERE actual_synced_at IS NULL
          AND txn_date IS NOT NULL
          AND amount_cents IS NOT NULL
        ORDER BY txn_date
        """
    ).fetchall()

    result = SyncResult()

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

            best = matches[0]

            if not dry_run:
                existing = (best.notes or "").strip()
                best.notes = f"{existing}\n{note}".strip() if existing else note

                db_conn.execute(
                    """
                    UPDATE retailer_transactions
                    SET actual_synced_at = datetime('now')
                    WHERE retailer_txn_id = ?
                    """,
                    (txn_id,),
                )
                db_conn.commit()

            result.synced += 1
            result.synced_rows.append(SyncedRow(
                retailer_txn_id=txn_id,
                order_id=order_id,
                txn_date=str(txn_date),
                amount_cents=amount_cents,
            ))

        if not dry_run and result.synced > 0:
            actual.commit()

    return result
