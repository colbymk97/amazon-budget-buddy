from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import unescape
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .base import (
    CollectResult,
    ParsedOrder,
    ParsedItem,
    ParsedRetailerTransaction,
    RetailerCollector,
)

MONEY_RE = re.compile(r"\$\s*([0-9,]+(?:\.[0-9]{2})?)")
ORDER_ID_RE = re.compile(r"(\d{3}-\d{7}-\d{7})")
DATE_RE = re.compile(r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})")
ORDER_FILE_RE = re.compile(r"order_(\d{3}-\d{7}-\d{7})\.html$")
ITEM_TITLE_LINK_RE = re.compile(
    r'<a[^>]+href="[^"]*ref_=ppx_hzod_title_dt_b_fed_asin_title_(\d+)_(\d+)[^"]*"[^>]*>(.*?)</a>',
    flags=re.IGNORECASE | re.DOTALL,
)
ITEM_IMAGE_QTY_RE = re.compile(
    r'ref_=ppx_hzod_image_dt_b_fed_asin_title_(\d+)_(\d+)[^"]*".{0,900}?'
    r'od-item-view-qty">\s*<span>\s*(\d+)\s*</span>',
    flags=re.IGNORECASE | re.DOTALL,
)


def _to_cents(text: str | None) -> int | None:
    if not text:
        return None
    m = MONEY_RE.search(text)
    if not m:
        return None
    value = m.group(1).replace(",", "")
    value = re.sub(r"[^0-9.]", "", value)
    if not value:
        return None
    try:
        cents = (Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return int(cents)


def _to_signed_cents(text: str | None) -> int | None:
    cents = _to_cents(text)
    if cents is None:
        return None
    if text and re.search(r"-\s*\$", text):
        return -cents
    return cents


def _extract_order_total_cents(order_page, content: str) -> int | None:
    # Prefer amounts near "Order total" labels, then fall back to any parseable amount.
    label_locators = [
        order_page.get_by_text("Order total", exact=False),
        order_page.get_by_text("Grand total", exact=False),
    ]
    for locator in label_locators:
        count = min(locator.count(), 10)
        for idx in range(count):
            try:
                text = locator.nth(idx).inner_text(timeout=1000)
            except Exception:
                continue
            cents = _to_cents(text)
            if cents is not None:
                return cents

    for match in MONEY_RE.finditer(content):
        cents = _to_cents(match.group(0))
        if cents is not None:
            return cents
    return None


def _extract_subtotals_block(content: str) -> str | None:
    marker = 'id="od-subtotals"'
    idx = content.find(marker)
    if idx == -1:
        return None
    # Keep a bounded window around the summary section.
    return content[idx : idx + 25000]


def _extract_labeled_amount_cents(block: str | None, label: str) -> int | None:
    if not block:
        return None
    pattern = re.compile(rf"{re.escape(label)}.*?\$\s*([0-9,]+(?:\.[0-9]{{2}})?)", re.IGNORECASE | re.DOTALL)
    m = pattern.search(block)
    if not m:
        return None
    return _to_cents(f"${m.group(1)}")


def _extract_labeled_signed_amount_cents(block: str | None, label: str) -> int | None:
    if not block:
        return None
    pattern = re.compile(
        rf"{re.escape(label)}.*?([+-]?\s*\$\s*[0-9,]+(?:\.[0-9]{{2}})?)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(block)
    if not m:
        return None
    return _to_signed_cents(m.group(1))


def _extract_order_date(content: str) -> str | None:
    date_block = re.search(r'data-component="orderDate".{0,600}', content, flags=re.IGNORECASE | re.DOTALL)
    if date_block:
        m = DATE_RE.search(date_block.group(0))
        if m:
            return _normalize_date_text(m.group(1))
    return None


def _extract_transaction_tag(content: str) -> str | None:
    m = re.search(r"transactionTag=([0-9]{3}-[0-9]{7}-[0-9]{7})", content)
    if m:
        return m.group(1)
    return None


def _clean_html_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_item_title_price_qty(content: str) -> list[tuple[str, int, int | None]]:
    pairs: list[tuple[str, int, int | None]] = []
    seen: set[str] = set()
    qty_by_key: dict[tuple[str, str], int] = {}

    for qm in ITEM_IMAGE_QTY_RE.finditer(content):
        try:
            qty_by_key[(qm.group(1), qm.group(2))] = max(1, int(qm.group(3)))
        except ValueError:
            continue

    title_matches = list(ITEM_TITLE_LINK_RE.finditer(content))
    for idx, m in enumerate(title_matches):
        block_key = (m.group(1), m.group(2))
        title = _clean_html_text(m.group(3))
        lower = title.lower()
        if len(title) <= 3:
            continue
        if title in seen:
            continue
        if "view your transactions" in lower:
            continue
        if "your orders" in lower:
            continue
        if "order details" in lower:
            continue
        if "invoice" in lower:
            continue

        qty = qty_by_key.get(block_key, 1)

        # Unit price usually appears shortly after title under data-component="unitPrice".
        next_start = title_matches[idx + 1].start() if idx + 1 < len(title_matches) else len(content)
        price_window = content[m.start() : min(next_start, m.start() + 5000)]
        price_block = re.search(
            r'data-component="unitPrice".{0,1600}',
            price_window,
            flags=re.IGNORECASE | re.DOTALL,
        )
        unit_price_cents = _to_cents(price_block.group(0)) if price_block else None
        subtotal_cents = (unit_price_cents * qty) if unit_price_cents is not None else None

        seen.add(title)
        pairs.append((title, qty, subtotal_cents))

    return pairs


def _alloc_proportional(total: int, weights: list[int]) -> list[int]:
    if not weights or sum(weights) <= 0:
        return [0 for _ in weights]
    raw = [total * w / sum(weights) for w in weights]
    base = [int(v) for v in raw]
    remainder = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:remainder]:
        base[i] += 1
    return base


def _parse_related_transactions(
    content: str,
    order_id: str,
    transaction_tag: str | None,
    fallback_amount_cents: int,
    fallback_last4: str | None,
    source_url: str,
) -> list[ParsedRetailerTransaction]:
    txns: list[ParsedRetailerTransaction] = []
    seen_ids: set[str] = set()

    # Parse visible line items on the related-transactions page.
    date_iter = list(re.finditer(r'<span>\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s*</span>', content))
    for i, dm in enumerate(date_iter):
        start = dm.start()
        end = date_iter[i + 1].start() if i + 1 < len(date_iter) else len(content)
        section = content[start:end]
        parsed_date = _normalize_date_text(dm.group(1))
        rows = re.findall(
            r'<span class="a-size-base a-text-bold">\s*([^<]+?)\s*</span>.*?'
            r'<span class="a-size-base-plus a-text-bold">\s*([+-]?\$\s*[0-9,]+(?:\.[0-9]{2})?)\s*</span>',
            section,
            flags=re.DOTALL,
        )
        for idx, (label, amount_text) in enumerate(rows, start=1):
            amount_cents = _to_signed_cents(amount_text)
            canonical = f"{order_id}|{parsed_date}|{label.strip()}|{amount_text.strip()}|{idx}"
            txn_hash = sha256(canonical.encode("utf-8")).hexdigest()[:16]
            txn_id = f"{order_id}-TX-{txn_hash}"
            if txn_id in seen_ids:
                continue
            seen_ids.add(txn_id)
            txns.append(
                ParsedRetailerTransaction(
                    retailer_txn_id=txn_id,
                    retailer="amazon",
                    order_id=order_id,
                    transaction_tag=transaction_tag,
                    txn_date=parsed_date,
                    amount_cents=amount_cents,
                    payment_last4=fallback_last4,
                    raw_label=label.strip(),
                    source_url=source_url,
                )
            )

    if txns:
        return txns

    # Structured payloads often include transactionId/amount/date fields.
    for m in re.finditer(r'"transactionId"\s*:\s*"([^"]+)"', content, re.IGNORECASE):
        txn_id = m.group(1).strip()
        if txn_id in seen_ids:
            continue
        window = content[max(0, m.start() - 500) : m.end() + 1200]
        amount_cents = _to_signed_cents(window)
        date_match = DATE_RE.search(window)
        txn_date = _normalize_date_text(date_match.group(1)) if date_match else None
        last4_match = re.search(r"ending in\s*(\d{4})", window, flags=re.IGNORECASE)
        payment_last4 = last4_match.group(1) if last4_match else fallback_last4
        seen_ids.add(txn_id)
        txns.append(
            ParsedRetailerTransaction(
                retailer_txn_id=txn_id,
                retailer="amazon",
                order_id=order_id,
                transaction_tag=transaction_tag,
                txn_date=txn_date,
                amount_cents=amount_cents,
                payment_last4=payment_last4,
                raw_label="parsed_related_transactions",
                source_url=source_url,
            )
        )

    # Fallback from query params links if structured payload missing.
    for txn_id in re.findall(r"[?&]transactionId=([A-Za-z0-9_-]+)", content):
        if txn_id in seen_ids:
            continue
        seen_ids.add(txn_id)
        txns.append(
            ParsedRetailerTransaction(
                retailer_txn_id=txn_id,
                retailer="amazon",
                order_id=order_id,
                transaction_tag=transaction_tag,
                txn_date=None,
                amount_cents=None,
                payment_last4=fallback_last4,
                raw_label="parsed_transactionId_query_param",
                source_url=source_url,
            )
        )

    if txns:
        return txns

    # Last-resort record so each order has a transaction row to link to.
    synthetic_id = f"{order_id}-T1"
    return [
        ParsedRetailerTransaction(
            retailer_txn_id=synthetic_id,
            retailer="amazon",
            order_id=order_id,
            transaction_tag=transaction_tag,
            txn_date=None,
            amount_cents=fallback_amount_cents,
            payment_last4=fallback_last4,
            raw_label="fallback_from_order_summary",
            source_url=source_url,
        )
    ]


def _normalize_date_text(text: str | None) -> str:
    if not text:
        return datetime.now().date().isoformat()

    clean = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean, fmt).date().isoformat()
        except ValueError:
            continue
    return datetime.now().date().isoformat()


def _reconcile_orders_and_shipments(conn: sqlite3.Connection, orders: list[ParsedOrder]) -> dict[str, int]:
    stats = {
        "orders_inserted": 0,
        "orders_updated": 0,
        "orders_unchanged": 0,
        "shipments_inserted": 0,
        "shipments_updated": 0,
        "shipments_unchanged": 0,
    }

    for o in orders:
        existing_order = conn.execute(
            """
            SELECT order_date, order_url, order_total_cents, tax_cents, shipping_cents, payment_last4
            FROM orders
            WHERE order_id = ?
            """,
            (o.order_id,),
        ).fetchone()

        if existing_order is None:
            conn.execute(
                """
                INSERT INTO orders (order_id, retailer, order_date, order_url, order_total_cents, tax_cents, shipping_cents, payment_last4)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    o.order_id,
                    "amazon",
                    o.order_date,
                    o.order_url,
                    o.order_total_cents,
                    o.tax_cents,
                    o.shipping_cents,
                    o.payment_last4,
                ),
            )
            stats["orders_inserted"] += 1
        else:
            changed = (
                existing_order["order_date"] != o.order_date
                or existing_order["order_url"] != o.order_url
                or existing_order["order_total_cents"] != o.order_total_cents
                or existing_order["tax_cents"] != o.tax_cents
                or existing_order["shipping_cents"] != o.shipping_cents
                or existing_order["payment_last4"] != o.payment_last4
            )
            if changed:
                conn.execute(
                    """
                    UPDATE orders
                    SET
                        order_date = ?,
                        order_url = ?,
                        order_total_cents = ?,
                        tax_cents = ?,
                        shipping_cents = ?,
                        payment_last4 = ?,
                        updated_at = datetime('now')
                    WHERE order_id = ?
                    """,
                    (
                        o.order_date,
                        o.order_url,
                        o.order_total_cents,
                        o.tax_cents,
                        o.shipping_cents,
                        o.payment_last4,
                        o.order_id,
                    ),
                )
                stats["orders_updated"] += 1
            else:
                stats["orders_unchanged"] += 1

        shipment_id = f"{o.order_id}-S1"
        existing_shipment = conn.execute(
            """
            SELECT ship_date, shipment_total_cents, status
            FROM shipments
            WHERE shipment_id = ?
            """,
            (shipment_id,),
        ).fetchone()

        if existing_shipment is None:
            conn.execute(
                """
                INSERT INTO shipments (shipment_id, order_id, ship_date, shipment_total_cents, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (shipment_id, o.order_id, o.order_date, o.order_total_cents, "unknown"),
            )
            stats["shipments_inserted"] += 1
        else:
            changed = (
                existing_shipment["ship_date"] != o.order_date
                or existing_shipment["shipment_total_cents"] != o.order_total_cents
                or existing_shipment["status"] != "unknown"
            )
            if changed:
                conn.execute(
                    """
                    UPDATE shipments
                    SET ship_date = ?, shipment_total_cents = ?, status = ?, updated_at = datetime('now')
                    WHERE shipment_id = ?
                    """,
                    (o.order_date, o.order_total_cents, "unknown", shipment_id),
                )
                stats["shipments_updated"] += 1
            else:
                stats["shipments_unchanged"] += 1

    return stats


def _reconcile_items(conn: sqlite3.Connection, items: list[ParsedItem]) -> dict[str, int]:
    stats = {
        "items_inserted": 0,
        "items_updated": 0,
        "items_unchanged": 0,
        "items_deleted": 0,
    }

    desired_by_order: dict[str, set[str]] = {}
    for i in items:
        desired_by_order.setdefault(i.order_id, set()).add(i.item_id)

    # Remove stale items from prior parser runs for orders in this reconcile batch.
    for order_id, desired_ids in desired_by_order.items():
        existing_ids = {
            row["item_id"]
            for row in conn.execute("SELECT item_id FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
        }
        stale_ids = sorted(existing_ids - desired_ids)
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            # Remove dependent allocation rows before deleting items.
            conn.execute(
                f"DELETE FROM order_item_transactions WHERE item_id IN ({placeholders})",
                (*stale_ids,),
            )
            conn.execute(
                f"DELETE FROM order_items WHERE order_id = ? AND item_id IN ({placeholders})",
                (order_id, *stale_ids),
            )
            stats["items_deleted"] += len(stale_ids)

    for i in items:
        shipment_id = f"{i.order_id}-S1"
        existing_item = conn.execute(
            """
            SELECT order_id, shipment_id, retailer_transaction_id, title, quantity, item_subtotal_cents, item_tax_cents
            FROM order_items
            WHERE item_id = ?
            """,
            (i.item_id,),
        ).fetchone()

        if existing_item is None:
            conn.execute(
                """
                INSERT INTO order_items (
                    item_id, order_id, shipment_id, retailer_transaction_id, title, quantity, item_subtotal_cents, item_tax_cents
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (i.item_id, i.order_id, shipment_id, None, i.title, i.quantity, i.item_subtotal_cents, 0),
            )
            stats["items_inserted"] += 1
        else:
            changed = (
                existing_item["order_id"] != i.order_id
                or existing_item["shipment_id"] != shipment_id
                or existing_item["retailer_transaction_id"] is not None
                or existing_item["title"] != i.title
                or existing_item["quantity"] != i.quantity
                or existing_item["item_subtotal_cents"] != i.item_subtotal_cents
                or existing_item["item_tax_cents"] != 0
            )
            if changed:
                conn.execute(
                    """
                    UPDATE order_items
                    SET
                        order_id = ?,
                        shipment_id = ?,
                        retailer_transaction_id = ?,
                        title = ?,
                        quantity = ?,
                        item_subtotal_cents = ?,
                        item_tax_cents = ?,
                        updated_at = datetime('now')
                    WHERE item_id = ?
                    """,
                    (i.order_id, shipment_id, None, i.title, i.quantity, i.item_subtotal_cents, 0, i.item_id),
                )
                stats["items_updated"] += 1
            else:
                stats["items_unchanged"] += 1

    return stats


def _reconcile_amazon_transactions(
    conn: sqlite3.Connection,
    parsed_by_order: dict[str, list[ParsedRetailerTransaction]],
) -> dict[str, int]:
    stats = {
        "amazon_txns_inserted": 0,
        "amazon_txns_updated": 0,
        "amazon_txns_unchanged": 0,
        "amazon_txns_deleted": 0,
    }

    for order_id, parsed_txns in parsed_by_order.items():
        desired_ids = {t.retailer_txn_id for t in parsed_txns}
        existing_ids = {
            row["retailer_txn_id"]
            for row in conn.execute(
                "SELECT retailer_txn_id FROM retailer_transactions WHERE order_id = ?",
                (order_id,),
            ).fetchall()
        }
        stale_ids = sorted(existing_ids - desired_ids)
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            # Clear parent pointers and dependent allocation rows before deleting transactions.
            conn.execute(
                f"UPDATE order_items SET retailer_transaction_id = NULL WHERE retailer_transaction_id IN ({placeholders})",
                (*stale_ids,),
            )
            conn.execute(
                f"DELETE FROM order_item_transactions WHERE retailer_txn_id IN ({placeholders})",
                (*stale_ids,),
            )
            conn.execute(
                f"DELETE FROM retailer_transactions WHERE order_id = ? AND retailer_txn_id IN ({placeholders})",
                (order_id, *stale_ids),
            )
            stats["amazon_txns_deleted"] += len(stale_ids)

        for t in parsed_txns:
            existing = conn.execute(
                """
                SELECT transaction_tag, txn_date, amount_cents, payment_last4, raw_label, source_url
                FROM retailer_transactions
                WHERE retailer_txn_id = ?
                """,
                (t.retailer_txn_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO retailer_transactions (
                        retailer_txn_id, retailer, order_id, transaction_tag, txn_date, amount_cents, payment_last4, raw_label, source_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.retailer_txn_id,
                        t.retailer,
                        t.order_id,
                        t.transaction_tag,
                        t.txn_date,
                        t.amount_cents,
                        t.payment_last4,
                        t.raw_label,
                        t.source_url,
                    ),
                )
                stats["amazon_txns_inserted"] += 1
            else:
                changed = (
                    existing["transaction_tag"] != t.transaction_tag
                    or existing["txn_date"] != t.txn_date
                    or existing["amount_cents"] != t.amount_cents
                    or existing["payment_last4"] != t.payment_last4
                    or existing["raw_label"] != t.raw_label
                    or existing["source_url"] != t.source_url
                )
                if changed:
                    conn.execute(
                        """
                        UPDATE retailer_transactions
                        SET
                            order_id = ?,
                            transaction_tag = ?,
                            txn_date = ?,
                            amount_cents = ?,
                            payment_last4 = ?,
                            raw_label = ?,
                            source_url = ?,
                            updated_at = datetime('now')
                        WHERE retailer_txn_id = ?
                        """,
                        (
                            t.order_id,
                            t.transaction_tag,
                            t.txn_date,
                            t.amount_cents,
                            t.payment_last4,
                            t.raw_label,
                            t.source_url,
                            t.retailer_txn_id,
                        ),
                    )
                    stats["amazon_txns_updated"] += 1
                else:
                    stats["amazon_txns_unchanged"] += 1

    return stats


def _reconcile_item_transaction_links(
    conn: sqlite3.Connection,
    items_by_order: dict[str, list[ParsedItem]],
    txns_by_order: dict[str, list[ParsedRetailerTransaction]],
) -> int:
    links_written = 0
    for order_id, items in items_by_order.items():
        txns = txns_by_order.get(order_id, [])
        if not items or not txns:
            continue

        # Reset prior links for this order.
        conn.execute(
            """
            DELETE FROM order_item_transactions
            WHERE item_id IN (SELECT item_id FROM order_items WHERE order_id = ?)
            """,
            (order_id,),
        )
        conn.execute("UPDATE order_items SET retailer_transaction_id = NULL WHERE order_id = ?", (order_id,))

        if len(txns) == 1:
            txn = txns[0]
            for item in items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO order_item_transactions (item_id, retailer_txn_id, allocated_amount_cents, method)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item.item_id, txn.retailer_txn_id, item.item_subtotal_cents, "single_transaction"),
                )
                conn.execute(
                    "UPDATE order_items SET retailer_transaction_id = ?, updated_at = datetime('now') WHERE item_id = ?",
                    (txn.retailer_txn_id, item.item_id),
                )
                links_written += 1
            continue

        # Multi-transaction order: proportional allocation based on transaction amounts.
        weights = [max(1, abs(t.amount_cents or 0)) for t in txns]
        for item in items:
            item_total = max(0, item.item_subtotal_cents)
            allocations = _alloc_proportional(item_total, weights)
            for idx, txn in enumerate(txns):
                allocated = allocations[idx]
                if allocated <= 0:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO order_item_transactions (item_id, retailer_txn_id, allocated_amount_cents, method)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item.item_id, txn.retailer_txn_id, allocated, "proportional_multi_transaction"),
                )
                links_written += 1

    return links_written


def _extract_order_ids_from_listing(page) -> list[str]:
    html = page.content()
    ids = re.findall(r"orderID=(\d{3}-\d{7}-\d{7})", html)
    deduped: list[str] = []
    seen: set[str] = set()
    for oid in ids:
        if oid == "000-0000000-8675309":
            continue
        if oid not in seen:
            seen.add(oid)
            deduped.append(oid)
    return deduped


def _parse_order_details(
    content: str,
    order_id: str,
    order_url: str | None = None,
) -> tuple[ParsedOrder | None, list[ParsedItem], str | None]:
    subtotals_block = _extract_subtotals_block(content)
    if not subtotals_block:
        return None, [], None

    # Prefer Order Summary fields in od-subtotals for stable parsing.
    grand_total_cents = _extract_labeled_amount_cents(subtotals_block, "Grand Total:")
    tax_cents = _extract_labeled_amount_cents(subtotals_block, "Estimated tax to be collected:")
    shipping_cents = _extract_labeled_amount_cents(subtotals_block, "Shipping & Handling:")
    total_before_tax_cents = _extract_labeled_amount_cents(subtotals_block, "Total before tax:")
    gift_card_cents = _extract_labeled_signed_amount_cents(subtotals_block, "Gift Card Amount:")
    if grand_total_cents is None and total_before_tax_cents is not None:
        grand_total_cents = total_before_tax_cents + (tax_cents or 0)

    pre_credit_total_cents = None
    if total_before_tax_cents is not None:
        pre_credit_total_cents = total_before_tax_cents + (tax_cents or 0)

    # On some orders Amazon applies gift card credits and shows "Grand Total: $0.00".
    # Preserve the actual order value by using the pre-credit total in that case.
    if (
        grand_total_cents is not None
        and pre_credit_total_cents is not None
        and gift_card_cents is not None
        and gift_card_cents < 0
        and grand_total_cents < pre_credit_total_cents
    ):
        grand_total_cents = pre_credit_total_cents

    order_total_cents = grand_total_cents

    order_date = _extract_order_date(content)
    if order_date is None:
        ordered_on_match = re.search(
            r"Ordered on\s*:?\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            content,
            flags=re.IGNORECASE,
        )
        if ordered_on_match:
            order_date = _normalize_date_text(ordered_on_match.group(1))

    payment_last4 = None
    last4_match = re.search(r"ending in\s*(\d{4})", content, flags=re.IGNORECASE)
    if last4_match:
        payment_last4 = last4_match.group(1)
    transaction_tag = _extract_transaction_tag(content)

    if order_total_cents is None:
        return None, [], transaction_tag

    parsed_order = ParsedOrder(
        order_id=order_id,
        order_date=order_date or datetime.now().date().isoformat(),
        order_url=order_url,
        order_total_cents=order_total_cents,
        tax_cents=tax_cents,
        shipping_cents=shipping_cents,
        payment_last4=payment_last4,
    )

    items: list[ParsedItem] = []
    title_price_qty = _extract_item_title_price_qty(content)
    if not title_price_qty:
        items.append(
            ParsedItem(
                item_id=f"{order_id}-I1",
                order_id=order_id,
                title="Unknown Amazon item",
                quantity=1,
                item_subtotal_cents=order_total_cents,
            )
        )
        return parsed_order, items, transaction_tag

    known_sum = sum(price for _, _, price in title_price_qty if price is not None)
    unknown_idx = [i for i, (_, _, price) in enumerate(title_price_qty) if price is None]
    resolved_prices = [price for _, _, price in title_price_qty]
    target_item_total_cents = total_before_tax_cents if total_before_tax_cents is not None else order_total_cents

    # Fill only missing prices from remaining amount.
    if unknown_idx:
        remaining = max(0, target_item_total_cents - known_sum)
        per_item = remaining // len(unknown_idx)
        remainder = remaining - (per_item * len(unknown_idx))
        for offset, idx in enumerate(unknown_idx):
            resolved_prices[idx] = per_item + (1 if offset < remainder else 0)
    elif known_sum > 0 and known_sum != target_item_total_cents:
        # Apply proportional normalization when order-level discounts/credits shift paid subtotal.
        weights = [max(1, p or 0) for p in resolved_prices]
        resolved_prices = _alloc_proportional(target_item_total_cents, weights)  # type: ignore[assignment]

    for i, (title, qty, _) in enumerate(title_price_qty, start=1):
        subtotal = resolved_prices[i - 1] or 0
        items.append(
            ParsedItem(
                item_id=f"{order_id}-I{i}",
                order_id=order_id,
                title=title,
                quantity=max(1, qty),
                item_subtotal_cents=subtotal,
            )
        )

    return parsed_order, items, transaction_tag


def _in_date_range(order_date: str, start_date: str | None, end_date: str | None) -> bool:
    if start_date and order_date < start_date:
        return False
    if end_date and order_date > end_date:
        return False
    return True


def _needs_auth(page) -> bool:
    url = page.url.lower()
    if any(token in url for token in ("ap/signin", "ap/cvf", "validatecaptcha", "challenge")):
        return True

    content = page.content().lower()
    markers = (
        "enter the characters you see",
        "one-time password",
        "two-step verification",
        "to continue, please sign in",
        "there was a problem",
    )
    return any(marker in content for marker in markers)


def _orders_page_markers_present(page) -> bool:
    content = page.content().lower()
    fallback_markers = (
        "your orders",
        "search all orders",
        "order-card",
    )
    return any(marker in content for marker in fallback_markers)


def _wait_for_orders_page_ready(page, timeout_ms: int = 12000) -> bool:
    url = page.url.lower()
    if "order-history" not in url and "your-orders" not in url:
        return False

    # Headless mode often reaches domcontentloaded before the order cards render.
    for _ in range(max(1, timeout_ms // 1000)):
        if _needs_auth(page):
            return False
        if _extract_order_ids_from_listing(page):
            return True
        if _orders_page_markers_present(page):
            return True
        page.wait_for_timeout(1000)
    return False


def _orders_page_ready(page) -> bool:
    return _wait_for_orders_page_ready(page, timeout_ms=12000)


def _launch_and_open_orders(p, profile_dir: Path, headless: bool):
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1400, "height": 1000},
    )
    page = context.new_page()
    page.goto("https://www.amazon.com/gp/your-account/order-history", wait_until="domcontentloaded")
    return context, page


def _resolve_saved_run_dir(output_dir: Path, saved_run_dir: Path | None) -> Path | None:
    if saved_run_dir:
        return saved_run_dir if saved_run_dir.exists() and saved_run_dir.is_dir() else None

    if not output_dir.exists():
        return None

    candidates = sorted(
        (
            p
            for p in output_dir.iterdir()
            if p.is_dir() and p.name != "browser_profile" and re.fullmatch(r"\d{8}_\d{6}", p.name)
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    for candidate in candidates:
        if any(candidate.glob("order_*.html")):
            return candidate
    return None


def _build_collect_result(
    conn: sqlite3.Connection,
    all_orders: list[ParsedOrder],
    all_items: list[ParsedItem],
    parsed_txns_by_order: dict[str, list[ParsedRetailerTransaction]],
    items_by_order: dict[str, list[ParsedItem]],
    notes: str,
    listing_pages_scanned: int = 0,
    discovered_orders: int = 0,
    known_orders_matched: int = 0,
) -> CollectResult:
    if not all_orders:
        return CollectResult(
            status="no_data",
            notes=notes,
            listing_pages_scanned=listing_pages_scanned,
            discovered_orders=discovered_orders,
            known_orders_matched=known_orders_matched,
        )

    order_stats = _reconcile_orders_and_shipments(conn, all_orders)
    item_stats = _reconcile_items(conn, all_items)
    txn_stats = _reconcile_amazon_transactions(conn, parsed_txns_by_order)
    link_count = _reconcile_item_transaction_links(conn, items_by_order, parsed_txns_by_order)
    conn.commit()

    return CollectResult(
        status="ok",
        notes=notes,
        orders_collected=len(all_orders),
        items_collected=len(all_items),
        orders_inserted=order_stats["orders_inserted"],
        orders_updated=order_stats["orders_updated"],
        orders_unchanged=order_stats["orders_unchanged"],
        shipments_inserted=order_stats["shipments_inserted"],
        shipments_updated=order_stats["shipments_updated"],
        shipments_unchanged=order_stats["shipments_unchanged"],
        items_inserted=item_stats["items_inserted"],
        items_updated=item_stats["items_updated"],
        items_unchanged=item_stats["items_unchanged"],
        items_deleted=item_stats["items_deleted"],
        amazon_txns_inserted=txn_stats["amazon_txns_inserted"],
        amazon_txns_updated=txn_stats["amazon_txns_updated"],
        amazon_txns_unchanged=txn_stats["amazon_txns_unchanged"],
        amazon_txns_deleted=txn_stats["amazon_txns_deleted"],
        item_txn_links_written=link_count,
        listing_pages_scanned=listing_pages_scanned,
        discovered_orders=discovered_orders,
        known_orders_matched=known_orders_matched,
    )


def collect_amazon(
    conn: sqlite3.Connection,
    output_dir: Path,
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
    output_dir.mkdir(parents=True, exist_ok=True)

    all_orders: list[ParsedOrder] = []
    all_items: list[ParsedItem] = []
    parsed_txns_by_order: dict[str, list[ParsedRetailerTransaction]] = {}
    items_by_order: dict[str, list[ParsedItem]] = {}
    listing_pages_scanned = 0
    discovered_order_count = 0
    known_order_id_set = set(known_order_ids or [])
    matched_known_order_ids: set[str] = set()
    if test_run:
        run_dir = _resolve_saved_run_dir(output_dir, saved_run_dir)
        if run_dir is None:
            return CollectResult(
                status="error",
                notes="No saved raw run directory found for --test-run.",
            )

        order_files = sorted(run_dir.glob("order_*.html"))
        if not order_files:
            return CollectResult(
                status="error",
                notes=f"No order_*.html files found under {run_dir}",
            )

        for order_file in order_files:
            if should_abort and should_abort():
                return CollectResult(status="cancelled", notes="Import cancelled by user.")
            if order_limit and len(all_orders) >= order_limit:
                break
            m = ORDER_FILE_RE.match(order_file.name)
            if not m:
                continue
            order_id = m.group(1)
            content = order_file.read_text(encoding="utf-8", errors="ignore")
            detail_url = f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
            parsed_order, parsed_items, transaction_tag = _parse_order_details(content, order_id, detail_url)
            if not parsed_order:
                continue
            if not _in_date_range(parsed_order.order_date, start_date, end_date):
                continue

            all_orders.append(parsed_order)
            all_items.extend(parsed_items)
            items_by_order[order_id] = parsed_items

            tx_file = run_dir / f"transactions_{order_id}.html"
            tx_source = str(tx_file)
            if tx_file.exists():
                tx_html = tx_file.read_text(encoding="utf-8", errors="ignore")
                parsed_txns = _parse_related_transactions(
                    content=tx_html,
                    order_id=order_id,
                    transaction_tag=transaction_tag,
                    fallback_amount_cents=parsed_order.order_total_cents,
                    fallback_last4=parsed_order.payment_last4,
                    source_url=tx_source,
                )
            else:
                parsed_txns = [
                    ParsedRetailerTransaction(
                        retailer_txn_id=f"{order_id}-T1",
                        retailer="amazon",
                        order_id=order_id,
                        transaction_tag=transaction_tag,
                        txn_date=None,
                        amount_cents=parsed_order.order_total_cents,
                        payment_last4=parsed_order.payment_last4,
                        raw_label="fallback_transactions_file_missing",
                        source_url=tx_source,
                    )
                ]
            parsed_txns_by_order[order_id] = parsed_txns

        notes = f"Test-run parsed saved raw pages from {run_dir}"
        if start_date or end_date:
            notes += f" | filters requested start_date={start_date}, end_date={end_date}"
        return _build_collect_result(
            conn,
            all_orders,
            all_items,
            parsed_txns_by_order,
            items_by_order,
            notes,
            listing_pages_scanned=listing_pages_scanned,
            discovered_orders=len(all_orders),
            known_orders_matched=0,
        )

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CollectResult(
            status="error",
            notes="Playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    run_dir = output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = user_data_dir or (output_dir / "browser_profile")
    profile_dir.mkdir(parents=True, exist_ok=True)
    seen_orders: set[str] = set()

    effective_max_pages = max_pages
    if effective_max_pages is None and order_limit:
        # Amazon order history typically shows 10 orders per page.
        effective_max_pages = max(1, (order_limit + 9) // 10)

    with sync_playwright() as p:
        if should_abort and should_abort():
            return CollectResult(status="cancelled", notes="Import cancelled by user.")
        context, page = _launch_and_open_orders(p, profile_dir, headless=headless)
        if not _orders_page_ready(page):
            context.close()
            if not allow_interactive_auth:
                return CollectResult(
                    status="auth_required",
                    notes=(
                        "Authentication required. Run collect-amazon interactively once to refresh session cookies "
                        "under data/raw/amazon/browser_profile."
                    ),
                )
            context, page = _launch_and_open_orders(p, profile_dir, headless=False)
            print("Authentication required. Complete Amazon login/MFA, navigate to Orders, then press Enter.")
            if not sys.stdin.isatty():
                context.close()
                return CollectResult(
                    status="auth_required",
                    notes=(
                        "Authentication required but no interactive TTY is available. "
                        "Run collect-amazon in an interactive terminal to refresh session cookies."
                    ),
                )
            input()
            page.goto("https://www.amazon.com/gp/your-account/order-history", wait_until="domcontentloaded")
            if not _orders_page_ready(page):
                context.close()
                return CollectResult(
                    status="auth_required",
                    notes="Could not establish authenticated session after manual login.",
                )

        order_ids: list[str] = []
        page_num = 1
        while True:
            if should_abort and should_abort():
                context.close()
                return CollectResult(status="cancelled", notes="Import cancelled by user.")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError:
                pass
            _wait_for_orders_page_ready(page, timeout_ms=8000)

            html = page.content()
            (run_dir / f"orders_page_{page_num}.html").write_text(html, encoding="utf-8")
            listing_pages_scanned = page_num

            current_ids = _extract_order_ids_from_listing(page)
            for oid in current_ids:
                if oid not in seen_orders:
                    seen_orders.add(oid)
                    order_ids.append(oid)
                if oid in known_order_id_set:
                    matched_known_order_ids.add(oid)
            discovered_order_count = len(order_ids)
            print(
                f"[orders] page={page_num} discovered_total={discovered_order_count} "
                f"matched_known={len(matched_known_order_ids)}"
            )

            if order_limit and len(order_ids) >= order_limit:
                break
            if (
                not order_limit
                and known_order_id_set
                and len(matched_known_order_ids) >= max(1, overlap_match_threshold)
            ):
                print("[orders] stopping after matching recent imported orders on listing pages")
                break
            if effective_max_pages is not None and page_num >= effective_max_pages:
                break

            next_link = page.locator("li.a-last a")
            if next_link.count() == 0:
                break
            next_link.first.click()
            page_num += 1

        if order_limit:
            order_ids = order_ids[:order_limit]

        consecutive_older_than_start = 0
        for idx, order_id in enumerate(order_ids, start=1):
            if should_abort and should_abort():
                context.close()
                return CollectResult(status="cancelled", notes="Import cancelled by user.")
            print(f"[details] processing {idx}/{len(order_ids)} order_id={order_id}")
            detail_url = f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
            detail_page = context.new_page()
            stop_due_to_age = False
            try:
                detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                detail_html = detail_page.content()
                (run_dir / f"order_{order_id}.html").write_text(detail_html, encoding="utf-8")

                parsed_order, parsed_items, transaction_tag = _parse_order_details(detail_html, order_id, detail_url)
                if parsed_order:
                    is_before_start = bool(start_date and parsed_order.order_date < start_date)
                    if _in_date_range(parsed_order.order_date, start_date, end_date):
                        consecutive_older_than_start = 0
                        all_orders.append(parsed_order)
                        all_items.extend(parsed_items)
                        items_by_order[order_id] = parsed_items

                        tx_url = (
                            f"https://www.amazon.com/cpe/yourpayments/transactions?transactionTag={transaction_tag}"
                            if transaction_tag
                            else f"https://www.amazon.com/cpe/yourpayments/transactions?transactionTag={order_id}"
                        )
                        tx_page = context.new_page()
                        parsed_txns = []
                        try:
                            tx_page.goto(tx_url, wait_until="domcontentloaded", timeout=30000)
                            tx_html = tx_page.content()
                            (run_dir / f"transactions_{order_id}.html").write_text(tx_html, encoding="utf-8")
                            parsed_txns = _parse_related_transactions(
                                content=tx_html,
                                order_id=order_id,
                                transaction_tag=transaction_tag,
                                fallback_amount_cents=parsed_order.order_total_cents,
                                fallback_last4=parsed_order.payment_last4,
                                source_url=tx_url,
                            )
                        except Exception:
                            # Preserve pipeline progress even if related-transactions page fails.
                            parsed_txns = [
                                ParsedRetailerTransaction(
                                    retailer_txn_id=f"{order_id}-T1",
                                    retailer="amazon",
                                    order_id=order_id,
                                    transaction_tag=transaction_tag,
                                    txn_date=None,
                                    amount_cents=parsed_order.order_total_cents,
                                    payment_last4=parsed_order.payment_last4,
                                    raw_label="fallback_transactions_page_error",
                                    source_url=tx_url,
                                )
                            ]
                        finally:
                            tx_page.close()
                        parsed_txns_by_order[order_id] = parsed_txns

                        print(
                            f"[details] saved order_id={order_id} "
                            f"orders_saved={len(all_orders)} items_saved={len(all_items)}"
                        )
                    else:
                        if is_before_start:
                            consecutive_older_than_start += 1
                        print(f"[details] skipped order_id={order_id} (outside date range)")
                        if (
                            stop_when_before_start_date
                            and start_date
                            and not end_date
                            and is_before_start
                            and consecutive_older_than_start >= 3
                        ):
                            print(
                                "[details] stopping early: encountered multiple consecutive "
                                "orders older than incremental start date"
                            )
                            stop_due_to_age = True
                else:
                    print(f"[details] skipped order_id={order_id} (no total parsed)")
            finally:
                detail_page.close()

            if stop_due_to_age:
                break
            if order_limit and idx >= order_limit:
                break

        context.close()

    notes = f"Saved raw pages to {run_dir}"
    if start_date or end_date:
        notes += f" | filters requested start_date={start_date}, end_date={end_date}"
    if known_order_id_set:
        notes += (
            f" | scanned_pages={listing_pages_scanned}"
            f" discovered_orders={discovered_order_count}"
            f" matched_known_orders={len(matched_known_order_ids)}"
        )
    if not all_orders:
        notes = f"No orders parsed. Raw pages saved under {run_dir}"
    return _build_collect_result(
        conn,
        all_orders,
        all_items,
        parsed_txns_by_order,
        items_by_order,
        notes,
        listing_pages_scanned=listing_pages_scanned,
        discovered_orders=discovered_order_count,
        known_orders_matched=len(matched_known_order_ids),
    )


class AmazonCollector(RetailerCollector):
    """Retailer adapter for Amazon order history."""

    RETAILER_ID = "amazon"

    def collect(
        self,
        conn,
        output_dir,
        *,
        start_date=None,
        end_date=None,
        order_limit=None,
        max_pages=None,
        headless=True,
        user_data_dir=None,
        test_run=False,
        saved_run_dir=None,
        allow_interactive_auth=True,
        should_abort=None,
        stop_when_before_start_date=False,
        known_order_ids=None,
        overlap_match_threshold=1,
    ) -> CollectResult:
        return collect_amazon(
            conn=conn,
            output_dir=output_dir,
            start_date=start_date,
            end_date=end_date,
            order_limit=order_limit,
            max_pages=max_pages,
            headless=headless,
            user_data_dir=user_data_dir,
            test_run=test_run,
            saved_run_dir=saved_run_dir,
            allow_interactive_auth=allow_interactive_auth,
            should_abort=should_abort,
            stop_when_before_start_date=stop_when_before_start_date,
            known_order_ids=known_order_ids,
            overlap_match_threshold=overlap_match_threshold,
        )
