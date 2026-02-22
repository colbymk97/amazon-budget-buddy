from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import streamlit as st


BASE_VIEWS = ["Home", "Orders", "Transactions", "Order Items"]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", type=Path, default=Path("data/amazon_spending.sqlite3"))
    return parser.parse_args()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _to_dollars(cents: int | None) -> float:
    return round((cents or 0) / 100.0, 2)


def _fmt_money(cents: int | None) -> str:
    value = _to_dollars(cents)
    return f"${value:,.2f}"


def _route() -> dict[str, str]:
    q = st.query_params
    return {
        "view": q.get("view", "Home"),
        "order_id": q.get("order_id", ""),
        "txn_id": q.get("txn_id", ""),
        "item_id": q.get("item_id", ""),
    }


def _set_route(view: str, order_id: str | None = None, txn_id: str | None = None, item_id: str | None = None) -> None:
    st.query_params.clear()
    st.query_params["view"] = view
    if order_id:
        st.query_params["order_id"] = order_id
    if txn_id:
        st.query_params["txn_id"] = txn_id
    if item_id:
        st.query_params["item_id"] = item_id
    st.rerun()


def _quality_stats(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM orders) AS orders_count,
            (SELECT COUNT(*) FROM orders WHERE order_total_cents = 0) AS orders_zero_total,
            (SELECT COUNT(*) FROM amazon_transactions) AS txns_count,
            (SELECT COUNT(*) FROM amazon_transactions WHERE amount_cents = 0) AS txns_zero_amount,
            (SELECT COUNT(*) FROM amazon_transactions WHERE raw_label LIKE 'fallback_%') AS txns_fallback,
            (SELECT COUNT(*) FROM order_items) AS items_count
        """
    ).fetchone()


def _date_bounds(conn: sqlite3.Connection) -> tuple[str, str]:
    minmax = conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    return minmax[0] or "2000-01-01", minmax[1] or "2100-01-01"


def _load_orders(conn: sqlite3.Connection, q: str, start_date: str, end_date: str, limit: int):
    sql = """
    SELECT
        o.order_id,
        o.order_date,
        o.order_url,
        o.order_total_cents,
        o.tax_cents,
        o.shipping_cents,
        o.payment_last4,
        COUNT(DISTINCT oi.item_id) AS item_count,
        COUNT(DISTINCT at.amazon_txn_id) AS txn_count
    FROM orders o
    LEFT JOIN order_items oi ON oi.order_id = o.order_id
    LEFT JOIN amazon_transactions at ON at.order_id = o.order_id
    WHERE o.order_date >= ? AND o.order_date <= ?
      AND (
        o.order_id LIKE ?
        OR EXISTS (SELECT 1 FROM order_items oi2 WHERE oi2.order_id = o.order_id AND oi2.title LIKE ?)
      )
    GROUP BY o.order_id, o.order_date, o.order_url, o.order_total_cents, o.tax_cents, o.shipping_cents, o.payment_last4
    ORDER BY o.order_date DESC, o.order_id DESC
    LIMIT ?
    """
    like = f"%{q.strip()}%"
    return conn.execute(sql, (start_date, end_date, like, like, limit)).fetchall()


def _load_transactions(conn: sqlite3.Connection, q: str, start_date: str, end_date: str, limit: int):
    sql = """
    SELECT
        at.amazon_txn_id,
        at.order_id,
        o.order_date,
        o.order_url,
        at.txn_date,
        at.amount_cents,
        at.payment_last4,
        at.raw_label,
        at.source_url
    FROM amazon_transactions at
    LEFT JOIN orders o ON o.order_id = at.order_id
    WHERE COALESCE(at.txn_date, o.order_date, '0000-00-00') >= ?
      AND COALESCE(at.txn_date, o.order_date, '9999-12-31') <= ?
      AND (
        at.order_id LIKE ?
        OR at.amazon_txn_id LIKE ?
        OR COALESCE(at.raw_label, '') LIKE ?
      )
    ORDER BY COALESCE(at.txn_date, o.order_date, '0000-00-00') DESC, at.amazon_txn_id DESC
    LIMIT ?
    """
    like = f"%{q.strip()}%"
    return conn.execute(sql, (start_date, end_date, like, like, like, limit)).fetchall()


def _load_order_items(conn: sqlite3.Connection, q: str, start_date: str, end_date: str, limit: int):
    sql = """
    SELECT
        oi.item_id,
        oi.order_id,
        o.order_date,
        o.order_url,
        oi.title,
        oi.quantity,
        oi.item_subtotal_cents,
        oi.item_tax_cents,
        oi.amazon_transaction_id
    FROM order_items oi
    LEFT JOIN orders o ON o.order_id = oi.order_id
    WHERE COALESCE(o.order_date, '0000-00-00') >= ?
      AND COALESCE(o.order_date, '9999-12-31') <= ?
      AND (
        oi.order_id LIKE ?
        OR oi.item_id LIKE ?
        OR COALESCE(oi.title, '') LIKE ?
      )
    ORDER BY COALESCE(o.order_date, '0000-00-00') DESC, oi.order_id DESC, oi.item_id ASC
    LIMIT ?
    """
    like = f"%{q.strip()}%"
    return conn.execute(sql, (start_date, end_date, like, like, like, limit)).fetchall()


def _order_detail(conn: sqlite3.Connection, order_id: str):
    return conn.execute(
        """
        SELECT o.*, COUNT(DISTINCT oi.item_id) AS item_count, COUNT(DISTINCT at.amazon_txn_id) AS txn_count
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.order_id
        LEFT JOIN amazon_transactions at ON at.order_id = o.order_id
        WHERE o.order_id = ?
        GROUP BY o.order_id
        """,
        (order_id,),
    ).fetchone()


def _transactions_for_order(conn: sqlite3.Connection, order_id: str):
    return conn.execute(
        """
        SELECT amazon_txn_id, txn_date, amount_cents, payment_last4, raw_label, source_url
        FROM amazon_transactions
        WHERE order_id = ?
        ORDER BY COALESCE(txn_date, '0000-00-00') DESC, amazon_txn_id
        """,
        (order_id,),
    ).fetchall()


def _items_for_order(conn: sqlite3.Connection, order_id: str):
    return conn.execute(
        """
        SELECT item_id, title, quantity, item_subtotal_cents, item_tax_cents, amazon_transaction_id
        FROM order_items
        WHERE order_id = ?
        ORDER BY item_id
        """,
        (order_id,),
    ).fetchall()


def _transaction_detail(conn: sqlite3.Connection, txn_id: str):
    return conn.execute(
        """
        SELECT at.*, o.order_date, o.order_url, o.order_total_cents, o.tax_cents
        FROM amazon_transactions at
        LEFT JOIN orders o ON o.order_id = at.order_id
        WHERE at.amazon_txn_id = ?
        """,
        (txn_id,),
    ).fetchone()


def _items_for_transaction(conn: sqlite3.Connection, txn_id: str):
    return conn.execute(
        """
        SELECT
            oi.item_id,
            oi.order_id,
            oi.title,
            oi.quantity,
            oi.item_subtotal_cents,
            oit.allocated_amount_cents,
            oit.method
        FROM order_item_transactions oit
        JOIN order_items oi ON oi.item_id = oit.item_id
        WHERE oit.amazon_txn_id = ?
        ORDER BY oi.item_id
        """,
        (txn_id,),
    ).fetchall()


def _item_detail(conn: sqlite3.Connection, item_id: str):
    return conn.execute(
        """
        SELECT oi.*, o.order_date, o.order_url, o.order_total_cents, o.tax_cents
        FROM order_items oi
        LEFT JOIN orders o ON o.order_id = oi.order_id
        WHERE oi.item_id = ?
        """,
        (item_id,),
    ).fetchone()


def _transactions_for_item(conn: sqlite3.Connection, item_id: str):
    return conn.execute(
        """
        SELECT at.amazon_txn_id, at.order_id, at.txn_date, at.amount_cents, at.raw_label,
               oit.allocated_amount_cents, oit.method
        FROM order_item_transactions oit
        JOIN amazon_transactions at ON at.amazon_txn_id = oit.amazon_txn_id
        WHERE oit.item_id = ?
        ORDER BY COALESCE(at.txn_date, '0000-00-00') DESC, at.amazon_txn_id
        """,
        (item_id,),
    ).fetchall()


def _filters(min_date: str, max_date: str) -> tuple[str, str, str, int]:
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    q = c1.text_input("Search", value="", placeholder="order id, transaction id, or title")
    start_date = c2.text_input("Start date", value=min_date)
    end_date = c3.text_input("End date", value=max_date)
    limit = c4.number_input("Rows", min_value=10, max_value=5000, value=500, step=10)
    return q, start_date, end_date, int(limit)


def _selectable_table(rows: list[dict], key: str):
    if not rows:
        st.info("No rows found for current filters.")
        return None

    try:
        event = st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=key,
            height=560,
        )
        selected = event.selection.rows
        if selected:
            return rows[selected[0]]
    except TypeError:
        st.dataframe(rows, use_container_width=True, hide_index=True, height=560)
        idx = st.selectbox("Select row", options=list(range(len(rows))), key=f"sel_{key}")
        if st.button("Open selected", key=f"open_{key}"):
            return rows[idx]
    return None


def _render_home(conn: sqlite3.Connection) -> None:
    st.subheader("Home Dashboard")
    quality = _quality_stats(conn)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Orders", quality["orders_count"])
    m2.metric("Transactions", quality["txns_count"])
    m3.metric("Order Items", quality["items_count"])
    m4.metric("Orders with $0 total", quality["orders_zero_total"])
    m5, m6 = st.columns(2)
    m5.metric("Transactions with $0", quality["txns_zero_amount"])
    m6.metric("Fallback transactions", quality["txns_fallback"])
    st.caption("Use the navigation above. Click rows in table views to open dedicated detail pages.")


def _render_orders_view(conn: sqlite3.Connection, min_date: str, max_date: str) -> None:
    st.subheader("Orders")
    q, start_date, end_date, limit = _filters(min_date, max_date)
    rows = _load_orders(conn, q=q, start_date=start_date, end_date=end_date, limit=limit)
    table = [
        {
            "order_id": r["order_id"],
            "order_date": r["order_date"],
            "order_total": _fmt_money(r["order_total_cents"]),
            "tax": _fmt_money(r["tax_cents"]),
            "shipping": _fmt_money(r["shipping_cents"]),
            "payment_last4": r["payment_last4"] or "",
            "items": r["item_count"],
            "transactions": r["txn_count"],
            "order_url": r["order_url"] or "",
        }
        for r in rows
    ]
    selected = _selectable_table(table, "orders_table")
    if selected:
        _set_route("Order Detail", order_id=selected["order_id"])


def _render_transactions_view(conn: sqlite3.Connection, min_date: str, max_date: str) -> None:
    st.subheader("Transactions")
    q, start_date, end_date, limit = _filters(min_date, max_date)
    rows = _load_transactions(conn, q=q, start_date=start_date, end_date=end_date, limit=limit)
    table = [
        {
            "amazon_txn_id": r["amazon_txn_id"],
            "txn_date": r["txn_date"] or "",
            "order_id": r["order_id"],
            "amount": _fmt_money(r["amount_cents"]),
            "payment_last4": r["payment_last4"] or "",
            "label": r["raw_label"] or "",
            "order_url": r["order_url"] or "",
        }
        for r in rows
    ]
    selected = _selectable_table(table, "txns_table")
    if selected:
        _set_route("Transaction Detail", txn_id=selected["amazon_txn_id"])


def _render_items_view(conn: sqlite3.Connection, min_date: str, max_date: str) -> None:
    st.subheader("Order Items")
    q, start_date, end_date, limit = _filters(min_date, max_date)
    rows = _load_order_items(conn, q=q, start_date=start_date, end_date=end_date, limit=limit)
    table = [
        {
            "item_id": r["item_id"],
            "order_id": r["order_id"],
            "order_date": r["order_date"] or "",
            "title": r["title"],
            "quantity": r["quantity"],
            "item_subtotal": _fmt_money(r["item_subtotal_cents"]),
            "item_tax": _fmt_money(r["item_tax_cents"]),
            "amazon_transaction_id": r["amazon_transaction_id"] or "",
            "order_url": r["order_url"] or "",
        }
        for r in rows
    ]
    selected = _selectable_table(table, "items_table")
    if selected:
        _set_route("Item Detail", item_id=selected["item_id"])


def _render_order_detail(conn: sqlite3.Connection, order_id: str) -> None:
    row = _order_detail(conn, order_id)
    if not row:
        st.error(f"Order not found: {order_id}")
        if st.button("Back to Orders"):
            _set_route("Orders")
        return

    c1, c2 = st.columns([1, 5])
    if c1.button("Back", key="back_order"):
        _set_route("Orders")
    c2.subheader(f"Order {order_id}")
    st.caption(
        f"Date {row['order_date']} | Total {_fmt_money(row['order_total_cents'])} | "
        f"Tax {_fmt_money(row['tax_cents'])} | Items {row['item_count']} | Transactions {row['txn_count']}"
    )
    if row["order_url"]:
        st.markdown(f"[Open Amazon order page]({row['order_url']})")

    st.markdown("**Associated Transactions**")
    tx_rows = _transactions_for_order(conn, order_id)
    tx_table = [
        {
            "amazon_txn_id": t["amazon_txn_id"],
            "txn_date": t["txn_date"] or "",
            "amount": _fmt_money(t["amount_cents"]),
            "payment_last4": t["payment_last4"] or "",
            "label": t["raw_label"] or "",
        }
        for t in tx_rows
    ]
    selected_tx = _selectable_table(tx_table, "order_detail_tx_table")
    if selected_tx:
        _set_route("Transaction Detail", txn_id=selected_tx["amazon_txn_id"])

    st.markdown("**Associated Items**")
    item_rows = _items_for_order(conn, order_id)
    item_table = [
        {
            "item_id": i["item_id"],
            "title": i["title"],
            "quantity": i["quantity"],
            "item_subtotal": _fmt_money(i["item_subtotal_cents"]),
            "item_tax": _fmt_money(i["item_tax_cents"]),
            "amazon_transaction_id": i["amazon_transaction_id"] or "",
        }
        for i in item_rows
    ]
    selected_item = _selectable_table(item_table, "order_detail_item_table")
    if selected_item:
        _set_route("Item Detail", item_id=selected_item["item_id"])


def _render_transaction_detail(conn: sqlite3.Connection, txn_id: str) -> None:
    row = _transaction_detail(conn, txn_id)
    if not row:
        st.error(f"Transaction not found: {txn_id}")
        if st.button("Back to Transactions"):
            _set_route("Transactions")
        return

    c1, c2 = st.columns([1, 5])
    if c1.button("Back", key="back_txn"):
        _set_route("Transactions")
    c2.subheader(f"Transaction {txn_id}")
    st.caption(
        f"Txn date {row['txn_date'] or 'n/a'} | Amount {_fmt_money(row['amount_cents'])} | "
        f"Label {row['raw_label'] or ''}"
    )

    st.markdown("**Parent Order**")
    order_cols = st.columns([3, 1])
    order_cols[0].write(
        f"Order {row['order_id']} | Date {row['order_date'] or 'n/a'} | "
        f"Total {_fmt_money(row['order_total_cents'])} | Tax {_fmt_money(row['tax_cents'])}"
    )
    if order_cols[1].button("Open Order", key=f"open_order_from_txn_{txn_id}"):
        _set_route("Order Detail", order_id=row["order_id"])
    if row["order_url"]:
        st.markdown(f"[Open Amazon order page]({row['order_url']})")

    st.markdown("**Associated Items**")
    items = _items_for_transaction(conn, txn_id)
    table = [
        {
            "item_id": i["item_id"],
            "order_id": i["order_id"],
            "title": i["title"],
            "quantity": i["quantity"],
            "item_subtotal": _fmt_money(i["item_subtotal_cents"]),
            "allocated_amount": _fmt_money(i["allocated_amount_cents"]),
            "method": i["method"],
        }
        for i in items
    ]
    selected = _selectable_table(table, "txn_detail_item_table")
    if selected:
        _set_route("Item Detail", item_id=selected["item_id"])


def _render_item_detail(conn: sqlite3.Connection, item_id: str) -> None:
    row = _item_detail(conn, item_id)
    if not row:
        st.error(f"Item not found: {item_id}")
        if st.button("Back to Order Items"):
            _set_route("Order Items")
        return

    c1, c2 = st.columns([1, 5])
    if c1.button("Back", key="back_item"):
        _set_route("Order Items")
    c2.subheader(f"Item {item_id}")
    st.write(row["title"])
    st.caption(
        f"Quantity {row['quantity']} | Subtotal {_fmt_money(row['item_subtotal_cents'])} | "
        f"Tax {_fmt_money(row['item_tax_cents'])}"
    )

    st.markdown("**Parent Order**")
    order_cols = st.columns([3, 1])
    order_cols[0].write(
        f"Order {row['order_id']} | Date {row['order_date'] or 'n/a'} | "
        f"Total {_fmt_money(row['order_total_cents'])} | Tax {_fmt_money(row['tax_cents'])}"
    )
    if order_cols[1].button("Open Order", key=f"open_order_from_item_{item_id}"):
        _set_route("Order Detail", order_id=row["order_id"])
    if row["order_url"]:
        st.markdown(f"[Open Amazon order page]({row['order_url']})")

    st.markdown("**Associated Transactions**")
    tx_rows = _transactions_for_item(conn, item_id)
    tx_table = [
        {
            "amazon_txn_id": t["amazon_txn_id"],
            "order_id": t["order_id"],
            "txn_date": t["txn_date"] or "",
            "txn_amount": _fmt_money(t["amount_cents"]),
            "allocated_amount": _fmt_money(t["allocated_amount_cents"]),
            "label": t["raw_label"] or "",
            "method": t["method"],
        }
        for t in tx_rows
    ]
    selected = _selectable_table(tx_table, "item_detail_tx_table")
    if selected:
        _set_route("Transaction Detail", txn_id=selected["amazon_txn_id"])


def main() -> None:
    args = _args()
    st.set_page_config(page_title="Amazon Spending Explorer", layout="wide")
    st.title("Amazon Spending Explorer")
    st.caption(f"Database: {args.db}")

    if not args.db.exists():
        st.error(f"Database not found: {args.db}")
        return

    conn = _connect(args.db)
    try:
        min_date, max_date = _date_bounds(conn)
        route = _route()
        current_view = route["view"] if route["view"] in BASE_VIEWS else "Home"

        nav = st.radio("Navigation", BASE_VIEWS, horizontal=True, index=BASE_VIEWS.index(current_view))
        if nav != current_view:
            _set_route(nav)

        view = route["view"]
        if view == "Home":
            _render_home(conn)
        elif view == "Orders":
            _render_orders_view(conn, min_date, max_date)
        elif view == "Transactions":
            _render_transactions_view(conn, min_date, max_date)
        elif view == "Order Items":
            _render_items_view(conn, min_date, max_date)
        elif view == "Order Detail":
            _render_order_detail(conn, route["order_id"])
        elif view == "Transaction Detail":
            _render_transaction_detail(conn, route["txn_id"])
        elif view == "Item Detail":
            _render_item_detail(conn, route["item_id"])
        else:
            _render_home(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
