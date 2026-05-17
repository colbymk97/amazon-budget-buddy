"""Textual TUI for browsing and operating the local SQLite database."""
from __future__ import annotations

from pathlib import Path


def run_tui(db_path: Path) -> None:
    """Launch the Textual app. Imported lazily from cli.py to avoid paying
    Textual's startup cost on every CLI invocation."""
    from .app import AmazonSpendingApp

    AmazonSpendingApp(db_path=db_path).run()
