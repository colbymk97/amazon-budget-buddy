from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import DataTable, Input, Static

from ..queries import list_transactions


def _fmt_money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


class TransactionsView(Container):
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("slash", "focus_search", "Search"),
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-transactions")
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        with Horizontal(id="txns-filters"):
            yield Input(placeholder="Search txn / order / label…", id="txns-search")
            yield Input(placeholder="Start (YYYY-MM-DD)", id="txns-start", classes="date-input")
            yield Input(placeholder="End (YYYY-MM-DD)", id="txns-end", classes="date-input")
        yield DataTable(id="txns-table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="txns-status")

    def on_mount(self) -> None:
        table = self.query_one("#txns-table", DataTable)
        table.add_columns("Txn ID", "Date", "Order", "Amount", "Card", "Label")
        self._load()

    def action_refresh(self) -> None:
        self._load()

    def action_focus_search(self) -> None:
        self.query_one("#txns-search", Input).focus()

    @on(Input.Changed)
    def _on_filter_change(self, event: Input.Changed) -> None:
        if event.input.id in ("txns-search", "txns-start", "txns-end"):
            self._load()

    def _load(self) -> None:
        search = self.query_one("#txns-search", Input).value
        start = self.query_one("#txns-start", Input).value.strip() or None
        end = self.query_one("#txns-end", Input).value.strip() or None
        rows = list_transactions(
            self.db_path, search=search, start_date=start, end_date=end, limit=500
        )

        table = self.query_one("#txns-table", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                r["retailer_txn_id"],
                r["txn_date"] or r["order_date"] or "—",
                r["order_id"],
                _fmt_money(r["amount_cents"]),
                r["payment_last4"] or "—",
                (r["raw_label"] or "—")[:40],
            )

        self.query_one("#txns-status", Static).update(
            f"[dim]{len(rows)} transaction(s) shown · r to refresh[/dim]"
        )
