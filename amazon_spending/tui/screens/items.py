from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import DataTable, Input, Static

from ..queries import list_items


def _fmt_money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


class ItemsView(Container):
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("slash", "focus_search", "Search"),
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-items")
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        with Horizontal(id="items-filters"):
            yield Input(placeholder="Search item title or order ID…", id="items-search")
            yield Input(placeholder="Start (YYYY-MM-DD)", id="items-start", classes="date-input")
            yield Input(placeholder="End (YYYY-MM-DD)", id="items-end", classes="date-input")
        yield DataTable(id="items-table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="items-status")

    def on_mount(self) -> None:
        table = self.query_one("#items-table", DataTable)
        table.add_columns("Date", "Order", "Title", "Qty", "Subtotal")
        self._load()

    def action_refresh(self) -> None:
        self._load()

    def action_focus_search(self) -> None:
        self.query_one("#items-search", Input).focus()

    @on(Input.Changed)
    def _on_filter_change(self, event: Input.Changed) -> None:
        if event.input.id in ("items-search", "items-start", "items-end"):
            self._load()

    def _load(self) -> None:
        search = self.query_one("#items-search", Input).value
        start = self.query_one("#items-start", Input).value.strip() or None
        end = self.query_one("#items-end", Input).value.strip() or None
        rows = list_items(self.db_path, search=search, start_date=start, end_date=end, limit=500)

        table = self.query_one("#items-table", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                r["order_date"] or "—",
                r["order_id"],
                (r["title"] or "")[:60],
                str(r["quantity"]),
                _fmt_money(r["item_subtotal_cents"]),
            )

        self.query_one("#items-status", Static).update(
            f"[dim]{len(rows)} item(s) shown · r to refresh[/dim]"
        )
