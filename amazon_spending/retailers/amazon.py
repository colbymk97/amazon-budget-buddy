from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path
from typing import Callable

from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession
from amazonorders.transactions import AmazonTransactions

from .base import (
    CollectResult,
    ParsedItem,
    ParsedOrder,
    ParsedRetailerTransaction,
    RetailerCollector,
)

RETAILER = "amazon"


def _dollars_to_cents(value: float | None) -> int | None:
    if value is None:
        return None
    return round(value * 100)


def _make_txn_id(order_id: str, txn_date: str | None, amount_cents: int | None) -> str:
    key = f"{order_id}|{txn_date}|{amount_cents}"
    return "amz-" + hashlib.sha1(key.encode()).hexdigest()[:16]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------
# DB reconciliation helpers
# ---------------------------------------------------------------------------

def _upsert_order(conn: sqlite3.Connection, o: ParsedOrder) -> tuple[bool, bool]:
    existing = conn.execute(
        "SELECT order_total_cents, tax_cents, shipping_cents, payment_last4 FROM orders WHERE order_id = ?",
        (o.order_id,),
    ).fetchone()

    if not existing:
        conn.execute(
            """
            INSERT INTO orders (order_id, retailer, order_date, order_url, order_total_cents,
                                tax_cents, shipping_cents, payment_last4)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (o.order_id, RETAILER, o.order_date, o.order_url, o.order_total_cents,
             o.tax_cents, o.shipping_cents, o.payment_last4),
        )
        return True, False

    changed = (
        existing["order_total_cents"] != o.order_total_cents
        or existing["tax_cents"] != o.tax_cents
        or existing["shipping_cents"] != o.shipping_cents
        or existing["payment_last4"] != o.payment_last4
    )
    if changed:
        conn.execute(
            """
            UPDATE orders
            SET order_date = ?, order_url = ?, order_total_cents = ?, tax_cents = ?,
                shipping_cents = ?, payment_last4 = ?, updated_at = datetime('now')
            WHERE order_id = ?
            """,
            (o.order_date, o.order_url, o.order_total_cents, o.tax_cents,
             o.shipping_cents, o.payment_last4, o.order_id),
        )
        return False, True
    return False, False


def _upsert_item(conn: sqlite3.Connection, item: ParsedItem) -> tuple[bool, bool]:
    existing = conn.execute(
        "SELECT title, quantity, item_subtotal_cents FROM order_items WHERE item_id = ?",
        (item.item_id,),
    ).fetchone()

    if not existing:
        conn.execute(
            """
            INSERT INTO order_items (item_id, order_id, title, quantity, item_subtotal_cents)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item.item_id, item.order_id, item.title, item.quantity, item.item_subtotal_cents),
        )
        return True, False

    changed = (
        existing["title"] != item.title
        or existing["quantity"] != item.quantity
        or existing["item_subtotal_cents"] != item.item_subtotal_cents
    )
    if changed:
        conn.execute(
            """
            UPDATE order_items
            SET title = ?, quantity = ?, item_subtotal_cents = ?, updated_at = datetime('now')
            WHERE item_id = ?
            """,
            (item.title, item.quantity, item.item_subtotal_cents, item.item_id),
        )
        return False, True
    return False, False


def _upsert_transaction(conn: sqlite3.Connection, txn: ParsedRetailerTransaction) -> tuple[bool, bool]:
    existing = conn.execute(
        "SELECT amount_cents, txn_date FROM retailer_transactions WHERE retailer_txn_id = ?",
        (txn.retailer_txn_id,),
    ).fetchone()

    if not existing:
        conn.execute(
            """
            INSERT INTO retailer_transactions (
                retailer_txn_id, retailer, order_id, transaction_tag, txn_date,
                amount_cents, payment_last4, raw_label, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (txn.retailer_txn_id, txn.retailer, txn.order_id, txn.transaction_tag,
             txn.txn_date, txn.amount_cents, txn.payment_last4, txn.raw_label, txn.source_url),
        )
        return True, False

    changed = existing["amount_cents"] != txn.amount_cents or existing["txn_date"] != txn.txn_date
    if changed:
        conn.execute(
            """
            UPDATE retailer_transactions
            SET txn_date = ?, amount_cents = ?, raw_label = ?, updated_at = datetime('now')
            WHERE retailer_txn_id = ?
            """,
            (txn.txn_date, txn.amount_cents, txn.raw_label, txn.retailer_txn_id),
        )
        return False, True
    return False, False


def _allocate_items_to_transaction(
    conn: sqlite3.Connection,
    order_id: str,
    txn_id: str,
) -> int:
    items = conn.execute(
        "SELECT item_id, item_subtotal_cents FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchall()
    written = 0
    for item in items:
        conn.execute(
            """
            INSERT INTO order_item_transactions (item_id, retailer_txn_id, allocated_amount_cents, method)
            VALUES (?, ?, ?, 'proportional')
            ON CONFLICT(item_id, retailer_txn_id) DO NOTHING
            """,
            (item["item_id"], txn_id, item["item_subtotal_cents"]),
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------

class AmazonCollector(RetailerCollector):
    RETAILER_ID = RETAILER

    def _get_session(self, conn: sqlite3.Connection) -> AmazonSession:
        creds = conn.execute(
            "SELECT email, password, otp_secret FROM retailer_credentials WHERE retailer = ?",
            (RETAILER,),
        ).fetchone()
        if not creds:
            raise RuntimeError(
                "Amazon credentials not configured. Add them in Settings before syncing."
            )
        session = AmazonSession(
            username=creds["email"],
            password=creds["password"],
            otp_secret_key=creds["otp_secret"],
        )
        session.login()
        return session

    def collect(
        self,
        conn: sqlite3.Connection,
        output_dir: Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        order_limit: int | None = None,
        should_abort: Callable[[], bool] | None = None,
        known_order_ids: list[str] | None = None,
    ) -> CollectResult:
        try:
            session = self._get_session(conn)
        except Exception as exc:
            return CollectResult(status="auth_required", notes=str(exc))

        result = CollectResult(status="ok", notes="")
        known_set = set(known_order_ids or [])

        today = date.today()
        start = date.fromisoformat(start_date) if start_date else date(today.year - 1, 1, 1)
        end = date.fromisoformat(end_date) if end_date else today

        years = list(range(start.year, end.year + 1))
        amazon_orders_client = AmazonOrders(session)
        all_parsed_orders: list[ParsedOrder] = []
        all_parsed_items: list[ParsedItem] = []

        for year in reversed(years):  # most recent first
            if should_abort and should_abort():
                return CollectResult(status="cancelled", notes="Cancelled by user.")

            try:
                year_orders = amazon_orders_client.get_order_history(year=year, full_details=True)
            except Exception as exc:
                return CollectResult(status="error", notes=f"Failed fetching {year} orders: {exc}")

            stop_year = False
            for order in year_orders:
                if should_abort and should_abort():
                    return CollectResult(status="cancelled", notes="Cancelled by user.")

                order_id = order.order_number
                if not order_id:
                    continue

                result.discovered_orders += 1

                order_date = _iso(order.order_placed_date)
                if order_date:
                    if order_date < start.isoformat():
                        continue
                    if order_date > end.isoformat():
                        continue

                if order_id in known_set:
                    result.known_orders_matched += 1
                    if result.known_orders_matched >= 3:
                        stop_year = True
                        break

                parsed = ParsedOrder(
                    order_id=order_id,
                    order_date=order_date or today.isoformat(),
                    order_url=order.order_details_link,
                    order_total_cents=_dollars_to_cents(order.grand_total) or 0,
                    tax_cents=_dollars_to_cents(order.estimated_tax),
                    shipping_cents=_dollars_to_cents(order.shipping_total),
                    payment_last4=(
                        str(order.payment_method_last_4) if order.payment_method_last_4 else None
                    ),
                )
                all_parsed_orders.append(parsed)
                result.orders_collected += 1

                for idx, lib_item in enumerate(order.items or []):
                    price_cents = _dollars_to_cents(lib_item.price) or 0
                    qty = lib_item.quantity or 1
                    all_parsed_items.append(ParsedItem(
                        item_id=f"{order_id}-item-{idx}",
                        order_id=order_id,
                        title=lib_item.title or "(unknown)",
                        quantity=qty,
                        item_subtotal_cents=price_cents * qty,
                    ))
                    result.items_collected += 1

                if order_limit and result.orders_collected >= order_limit:
                    stop_year = True
                    break

            if stop_year:
                break

        # Transactions: compute days back from start date
        days_back = max(7, (today - start).days + 2)
        amazon_txns_client = AmazonTransactions(session)
        parsed_transactions: list[ParsedRetailerTransaction] = []

        try:
            raw_txns = amazon_txns_client.get_transactions(days=days_back)
        except Exception as exc:
            raw_txns = []
            result.notes = f"Warning: could not fetch transactions ({exc}). Orders were imported."

        order_ids_collected = {o.order_id for o in all_parsed_orders}

        for txn in raw_txns:
            order_id = txn.order_number
            if not order_id or order_id not in order_ids_collected:
                continue

            txn_date = _iso(txn.completed_date)
            amount_cents = _dollars_to_cents(txn.grand_total)
            # Negate: library gives positive for purchases; our convention is negative for charges
            if amount_cents is not None:
                amount_cents = -amount_cents

            parsed_transactions.append(ParsedRetailerTransaction(
                retailer_txn_id=_make_txn_id(order_id, txn_date, amount_cents),
                retailer=RETAILER,
                order_id=order_id,
                transaction_tag=None,
                txn_date=txn_date,
                amount_cents=amount_cents,
                payment_last4=None,
                raw_label="Refund" if txn.is_refund else "Order",
                source_url=txn.order_details_link,
            ))

        # Persist
        for order in all_parsed_orders:
            inserted, updated = _upsert_order(conn, order)
            if inserted:
                result.orders_inserted += 1
            elif updated:
                result.orders_updated += 1
            else:
                result.orders_unchanged += 1

        for item in all_parsed_items:
            inserted, updated = _upsert_item(conn, item)
            if inserted:
                result.items_inserted += 1
            elif updated:
                result.items_updated += 1
            else:
                result.items_unchanged += 1

        for txn in parsed_transactions:
            order_exists = conn.execute(
                "SELECT 1 FROM orders WHERE order_id = ?", (txn.order_id,)
            ).fetchone()
            if not order_exists:
                continue
            inserted, updated = _upsert_transaction(conn, txn)
            if inserted:
                result.amazon_txns_inserted += 1
                _allocate_items_to_transaction(conn, txn.order_id, txn.retailer_txn_id)
            elif updated:
                result.amazon_txns_updated += 1
            else:
                result.amazon_txns_unchanged += 1

        conn.commit()
        return result
