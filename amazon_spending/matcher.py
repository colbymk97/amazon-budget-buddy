from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass
class MatchResult:
    txn_id: str
    matches_written: int


def _days_between(a: str, b: str | None) -> int:
    if not b:
        return 999
    da = date.fromisoformat(a)
    db = date.fromisoformat(b)
    return abs((da - db).days)


def _alloc_proportional(total: int, weights: list[int]) -> list[int]:
    if not weights or sum(weights) <= 0:
        return []
    raw = [total * w / sum(weights) for w in weights]
    base = [int(v) for v in raw]
    remainder = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:remainder]:
        base[i] += 1
    return base


def _shipment_candidates(conn: sqlite3.Connection, amount_cents: int):
    return conn.execute(
        """
        SELECT s.shipment_id, s.order_id, s.ship_date
        FROM shipments s
        WHERE s.shipment_total_cents = ?
        """,
        (amount_cents,),
    ).fetchall()


def _order_candidates(conn: sqlite3.Connection, amount_cents: int):
    return conn.execute(
        """
        SELECT o.order_id, o.order_date
        FROM orders o
        WHERE o.order_total_cents = ?
        """,
        (amount_cents,),
    ).fetchall()


def _write_item_matches(
    conn: sqlite3.Connection,
    txn_id: str,
    order_id: str,
    shipment_id: str | None,
    amount_cents: int,
    method: str,
    confidence: float,
) -> int:
    if shipment_id:
        items = conn.execute(
            """
            SELECT item_id, item_subtotal_cents
            FROM order_items
            WHERE shipment_id = ?
            ORDER BY item_id
            """,
            (shipment_id,),
        ).fetchall()
    else:
        items = conn.execute(
            """
            SELECT item_id, item_subtotal_cents
            FROM order_items
            WHERE order_id = ?
            ORDER BY item_id
            """,
            (order_id,),
        ).fetchall()

    if not items:
        conn.execute(
            """
            INSERT INTO matches (txn_id, order_id, shipment_id, item_id, allocated_amount_cents, confidence, method)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (txn_id, order_id, shipment_id, amount_cents, confidence, method),
        )
        return 1

    alloc = _alloc_proportional(amount_cents, [r["item_subtotal_cents"] for r in items])
    rows = [
        (
            txn_id,
            order_id,
            shipment_id,
            item["item_id"],
            alloc[idx],
            confidence,
            method,
        )
        for idx, item in enumerate(items)
    ]
    conn.executemany(
        """
        INSERT INTO matches (txn_id, order_id, shipment_id, item_id, allocated_amount_cents, confidence, method)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def run_matching(conn: sqlite3.Connection, amazon_only: bool = True) -> list[MatchResult]:
    txns = conn.execute(
        """
        SELECT t.txn_id, t.posted_date, t.amount_cents, t.merchant_raw
        FROM transactions t
        WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.txn_id = t.txn_id)
        ORDER BY t.posted_date
        """
    ).fetchall()

    results: list[MatchResult] = []

    for txn in txns:
        merchant_raw = txn["merchant_raw"].lower()
        if amazon_only and "amazon" not in merchant_raw:
            continue

        written = 0

        shipment_candidates = _shipment_candidates(conn, txn["amount_cents"])
        if shipment_candidates:
            best = min(shipment_candidates, key=lambda r: _days_between(txn["posted_date"], r["ship_date"]))
            best_delta = _days_between(txn["posted_date"], best["ship_date"])
            confidence = 0.95 if best_delta <= 3 else 0.85
            written = _write_item_matches(
                conn,
                txn["txn_id"],
                best["order_id"],
                best["shipment_id"],
                txn["amount_cents"],
                method="exact_shipment",
                confidence=confidence,
            )
        else:
            order_candidates = _order_candidates(conn, txn["amount_cents"])
            if order_candidates:
                best = min(order_candidates, key=lambda r: _days_between(txn["posted_date"], r["order_date"]))
                best_delta = _days_between(txn["posted_date"], best["order_date"])
                confidence = 0.90 if best_delta <= 5 else 0.80
                written = _write_item_matches(
                    conn,
                    txn["txn_id"],
                    best["order_id"],
                    None,
                    txn["amount_cents"],
                    method="exact_order",
                    confidence=confidence,
                )

        if written > 0:
            results.append(MatchResult(txn_id=txn["txn_id"], matches_written=written))

    conn.commit()
    return results
