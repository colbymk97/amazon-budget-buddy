from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from ..queries import list_orders, order_detail


def _fmt_money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


class OrderDetailModal(ModalScreen):
    """Modal showing an order's items + transactions."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, db_path: Path, order_id: str) -> None:
        super().__init__()
        self.db_path = db_path
        self.order_id = order_id

    def compose(self) -> ComposeResult:
        with Vertical(id="order-modal"):
            yield Static(id="order-modal-header")
            yield Static("Items", classes="modal-section")
            yield DataTable(id="order-modal-items", zebra_stripes=True)
            yield Static("Transactions", classes="modal-section")
            yield DataTable(id="order-modal-txns", zebra_stripes=True)
            yield Static("[dim]esc to close[/dim]", id="order-modal-footer")

    def on_mount(self) -> None:
        items_tbl = self.query_one("#order-modal-items", DataTable)
        items_tbl.add_columns("Item ID", "Title", "Qty", "Subtotal")
        txns_tbl = self.query_one("#order-modal-txns", DataTable)
        txns_tbl.add_columns("Txn ID", "Date", "Amount", "Label")

        detail = order_detail(self.db_path, self.order_id)
        if not detail:
            self.query_one("#order-modal-header", Static).update(
                f"[red]Order {self.order_id} not found.[/red]"
            )
            return

        order = detail["order"]
        self.query_one("#order-modal-header", Static).update(
            f"[b]{order['order_id']}[/b]  ·  {order['order_date']}  ·  "
            f"total {_fmt_money(order['order_total_cents'])}  ·  "
            f"tax {_fmt_money(order['tax_cents'])}  ·  "
            f"ship {_fmt_money(order['shipping_cents'])}  ·  "
            f"card ****{order['payment_last4'] or '—'}"
        )
        for it in detail["items"]:
            items_tbl.add_row(
                it["item_id"],
                it["title"],
                str(it["quantity"]),
                _fmt_money(it["item_subtotal_cents"]),
            )
        for tx in detail["transactions"]:
            txns_tbl.add_row(
                tx["retailer_txn_id"],
                tx["txn_date"] or "—",
                _fmt_money(tx["amount_cents"]),
                tx["raw_label"] or "—",
            )


class OrdersView(Container):
    """Browseable list of orders with search + date filter."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("slash", "focus_search", "Search"),
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-orders")
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        with Horizontal(id="orders-filters"):
            yield Input(placeholder="Search order ID or item title…", id="orders-search")
            yield Input(placeholder="Start (YYYY-MM-DD)", id="orders-start", classes="date-input")
            yield Input(placeholder="End (YYYY-MM-DD)", id="orders-end", classes="date-input")
        yield DataTable(id="orders-table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="orders-status")

    def on_mount(self) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.add_columns("Order ID", "Date", "Total", "Items", "Txns", "Card")
        self._load()

    def action_refresh(self) -> None:
        self._load()

    def action_focus_search(self) -> None:
        self.query_one("#orders-search", Input).focus()

    @on(Input.Changed)
    def _on_filter_change(self, event: Input.Changed) -> None:
        if event.input.id in ("orders-search", "orders-start", "orders-end"):
            self._load()

    @on(DataTable.RowSelected, "#orders-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#orders-table", DataTable)
        row = table.get_row(event.row_key)
        order_id = str(row[0])
        self.app.push_screen(OrderDetailModal(self.db_path, order_id))

    def _load(self) -> None:
        search = self.query_one("#orders-search", Input).value
        start = self.query_one("#orders-start", Input).value.strip() or None
        end = self.query_one("#orders-end", Input).value.strip() or None
        rows = list_orders(self.db_path, search=search, start_date=start, end_date=end, limit=500)

        table = self.query_one("#orders-table", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                r["order_id"],
                r["order_date"],
                _fmt_money(r["order_total_cents"]),
                str(r["item_count"]),
                str(r["txn_count"]),
                r["payment_last4"] or "—",
            )

        self.query_one("#orders-status", Static).update(
            f"[dim]{len(rows)} order(s) shown · enter to open detail · r to refresh[/dim]"
        )
