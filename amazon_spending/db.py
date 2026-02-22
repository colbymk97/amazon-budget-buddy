from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path("data/amazon_spending.sqlite3")


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    item_cols = {row["name"] for row in conn.execute("PRAGMA table_info(order_items)").fetchall()}
    if item_cols and "amazon_transaction_id" not in item_cols:
        conn.execute("ALTER TABLE order_items ADD COLUMN amazon_transaction_id TEXT")
    order_cols = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if order_cols and "order_url" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN order_url TEXT")
    txn_cols = {row["name"] for row in conn.execute("PRAGMA table_info(amazon_transactions)").fetchall()}
    if txn_cols and "budget_category_id" not in txn_cols:
        conn.execute("ALTER TABLE amazon_transactions ADD COLUMN budget_category_id INTEGER")
    if txn_cols and "budget_subcategory_id" not in txn_cols:
        conn.execute("ALTER TABLE amazon_transactions ADD COLUMN budget_subcategory_id INTEGER")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS budget_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS budget_subcategories (
            subcategory_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(category_id) REFERENCES budget_categories(category_id),
            UNIQUE(category_id, name)
        );

        CREATE INDEX IF NOT EXISTS idx_amazon_transactions_budget_category_id
            ON amazon_transactions(budget_category_id);
        CREATE INDEX IF NOT EXISTS idx_amazon_transactions_budget_subcategory_id
            ON amazon_transactions(budget_subcategory_id);
        CREATE INDEX IF NOT EXISTS idx_budget_subcategories_category_id
            ON budget_subcategories(category_id);
        """
    )


def init_db(conn: sqlite3.Connection) -> None:
    # Migration guard: existing DBs may have order_items without amazon_transaction_id,
    # but schema now creates an index on that column.
    _ensure_columns(conn)
    schema_path = Path(__file__).parent / "sql" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    _ensure_columns(conn)
    conn.commit()


def executemany(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> None:
    conn.executemany(sql, rows)
    conn.commit()
