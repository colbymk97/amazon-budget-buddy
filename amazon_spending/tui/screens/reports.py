from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import DataTable, Select, Static

from ..queries import available_months, monthly_summary, top_orders_for_month


def _fmt_money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


class ReportsView(Container):
    BINDINGS = [("r", "refresh", "Refresh")]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-reports")
        self.db_path = db_path
        self._months: list[str] = []

    def compose(self) -> ComposeResult:
        # Read available months once at compose time so we can hand the Select
        # a non-empty list (Textual requires this when allow_blank=False).
        self._months = available_months(self.db_path)
        options = [(m, m) for m in self._months] or [("(no data)", "")]
        with Horizontal(id="reports-controls"):
            yield Static("Month:", classes="reports-label")
            yield Select(options, id="reports-month", allow_blank=False, value=options[0][1])
        yield Static("", id="reports-metrics")
        yield Static("Top orders", classes="modal-section")
        yield DataTable(id="reports-top-orders", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#reports-top-orders", DataTable)
        table.add_columns("Order ID", "Date", "Total", "Items", "Txns")

        if self._months:
            self._show_month(self._months[0])
        else:
            self.query_one("#reports-metrics", Static).update(
                "[yellow]No order data yet.[/yellow] Run a collect first."
            )

    def action_refresh(self) -> None:
        select = self.query_one("#reports-month", Select)
        if select.value:
            self._show_month(str(select.value))

    @on(Select.Changed, "#reports-month")
    def _on_month_change(self, event: Select.Changed) -> None:
        if event.value:
            self._show_month(str(event.value))

    def _show_month(self, month: str) -> None:
        summary = monthly_summary(self.db_path, month)
        metrics = self.query_one("#reports-metrics", Static)
        metrics.update(
            f"[b]{month}[/b]\n"
            f"Net spend:           [b]{_fmt_money(summary.net_spend_cents)}[/b]\n"
            f"Gross order total:   [b]{_fmt_money(summary.gross_order_total_cents)}[/b]\n"
            f"Orders:              [b]{summary.order_count:,}[/b]\n"
            f"Transactions:        [b]{summary.transaction_count:,}[/b]\n"
            f"Items:               [b]{summary.item_count:,}[/b]"
        )

        rows = top_orders_for_month(self.db_path, month, limit=30)
        table = self.query_one("#reports-top-orders", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                r["order_id"],
                r["order_date"],
                _fmt_money(r["order_total_cents"]),
                str(r["item_count"]),
                str(r["txn_count"]),
            )
