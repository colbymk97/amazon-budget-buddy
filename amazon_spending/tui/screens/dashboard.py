from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Static

from ..queries import dashboard_overview


def _fmt_money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


class DashboardView(Container):
    """Database overview: per-retailer counts, dates, last import status."""

    BINDINGS = [("r", "refresh", "Refresh")]

    def __init__(self, db_path: Path) -> None:
        super().__init__(id="view-dashboard")
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield Static("Database overview", id="dashboard-title")
        yield DataTable(id="dashboard-retailers", zebra_stripes=True, cursor_type="row")
        yield Static("", id="dashboard-summary")

    def on_mount(self) -> None:
        table = self.query_one("#dashboard-retailers", DataTable)
        table.add_columns(
            "Retailer",
            "Orders",
            "Transactions",
            "First order",
            "Latest order",
            "Last import",
            "Status",
            "Account",
        )
        self._load()

    def action_refresh(self) -> None:
        self._load()

    def _load(self) -> None:
        table = self.query_one("#dashboard-retailers", DataTable)
        table.clear()
        summary = self.query_one("#dashboard-summary", Static)

        rows = dashboard_overview(self.db_path)
        if not rows:
            summary.update(
                "[yellow]No data yet.[/yellow] Run [b]amazon-spending login[/b] then "
                "[b]Commands → Collect[/b] to import."
            )
            return

        total_orders = 0
        total_txns = 0
        for r in rows:
            total_orders += r.orders
            total_txns += r.transactions
            table.add_row(
                r.retailer,
                f"{r.orders:,}",
                f"{r.transactions:,}",
                r.first_order_date or "—",
                r.latest_order_date or "—",
                (r.last_import_finished_at or "—").split(".")[0],
                r.last_import_status or "—",
                r.bound_account or "—",
            )
        summary.update(
            f"Total: [b]{total_orders:,}[/b] orders   "
            f"[b]{total_txns:,}[/b] transactions"
        )
