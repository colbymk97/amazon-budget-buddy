from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Footer, Header, ListItem, ListView, Static

from .screens import (
    CommandsView,
    DashboardView,
    ItemsView,
    OrdersView,
    ReportsView,
    TransactionsView,
)


_SECTIONS: list[tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("orders", "Orders"),
    ("transactions", "Transactions"),
    ("items", "Items"),
    ("reports", "Reports"),
    ("commands", "Commands"),
]


class AmazonSpendingApp(App):
    CSS_PATH = "tui.css"
    TITLE = "amazon-spending"
    SUB_TITLE = "local SQLite browser"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+d", "quit", "Quit"),
        ("1", "select(0)", "Dashboard"),
        ("2", "select(1)", "Orders"),
        ("3", "select(2)", "Transactions"),
        ("4", "select(3)", "Items"),
        ("5", "select(4)", "Reports"),
        ("6", "select(5)", "Commands"),
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("amazon-spending", id="brand")
                yield Static(f"[dim]{self.db_path}[/dim]", id="brand-db")
                yield ListView(
                    *[
                        ListItem(Static(label), id=f"nav-{key}")
                        for key, label in _SECTIONS
                    ],
                    id="nav",
                )
            with ContentSwitcher(initial="view-dashboard", id="switcher"):
                yield DashboardView(self.db_path)
                yield OrdersView(self.db_path)
                yield TransactionsView(self.db_path)
                yield ItemsView(self.db_path)
                yield ReportsView(self.db_path)
                yield CommandsView(self.db_path)
        yield Footer()

    @on(ListView.Selected, "#nav")
    def _on_nav(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        key = item_id.removeprefix("nav-")
        self._activate(key)

    def action_select(self, idx: int) -> None:
        if 0 <= idx < len(_SECTIONS):
            key, _label = _SECTIONS[idx]
            nav = self.query_one("#nav", ListView)
            nav.index = idx
            self._activate(key)

    def _activate(self, key: str) -> None:
        switcher = self.query_one("#switcher", ContentSwitcher)
        switcher.current = f"view-{key}"
