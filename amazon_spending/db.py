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


def _migrate_to_multi_retailer(conn: sqlite3.Connection) -> None:
    """One-time migration: rename amazon_* tables/columns → retailer_*.

    Guards every step with existence checks so it is safe to run on a fresh
    database (no-ops) as well as on an existing Amazon-only database.
    Requires SQLite ≥ 3.25 (RENAME COLUMN) and ≥ 3.26 (RENAME TABLE updates
    FK references). Python 3.9+ ships SQLite ≥ 3.31, so this is always met.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    def _cols(table: str) -> set[str]:
        if table not in tables:
            return set()
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    # 1. Rename the top-level table
    if "amazon_transactions" in tables and "retailer_transactions" not in tables:
        conn.execute("ALTER TABLE amazon_transactions RENAME TO retailer_transactions")
        tables.discard("amazon_transactions")
        tables.add("retailer_transactions")

    # 2. Rename primary-key column on retailer_transactions
    rt_cols = _cols("retailer_transactions")
    if "amazon_txn_id" in rt_cols:
        conn.execute(
            "ALTER TABLE retailer_transactions RENAME COLUMN amazon_txn_id TO retailer_txn_id"
        )

    # 3. Add retailer column to retailer_transactions (backfill as 'amazon')
    rt_cols = _cols("retailer_transactions")
    if rt_cols and "retailer" not in rt_cols:
        conn.execute(
            "ALTER TABLE retailer_transactions ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'"
        )

    # 4. Add retailer column to orders (backfill as 'amazon')
    order_cols = _cols("orders")
    if order_cols and "retailer" not in order_cols:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'"
        )

    # 5. Rename FK column in order_items
    item_cols = _cols("order_items")
    if "amazon_transaction_id" in item_cols:
        conn.execute(
            "ALTER TABLE order_items RENAME COLUMN amazon_transaction_id TO retailer_transaction_id"
        )

    # 6. Rename FK/PK column in order_item_transactions
    oit_cols = _cols("order_item_transactions")
    if "amazon_txn_id" in oit_cols:
        conn.execute(
            "ALTER TABLE order_item_transactions RENAME COLUMN amazon_txn_id TO retailer_txn_id"
        )

    conn.commit()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing in older databases (post-migration)."""

    def _cols(table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}

    # order_items: ensure retailer_transaction_id exists
    item_cols = _cols("order_items")
    if item_cols and "retailer_transaction_id" not in item_cols and "amazon_transaction_id" not in item_cols:
        conn.execute("ALTER TABLE order_items ADD COLUMN retailer_transaction_id TEXT")

    # orders: ensure order_url and retailer exist
    order_cols = _cols("orders")
    if order_cols and "order_url" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN order_url TEXT")
    if order_cols and "retailer" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'")

    # retailer_transactions: ensure budget and retailer columns
    txn_cols = _cols("retailer_transactions")
    if txn_cols:
        if "budget_category_id" not in txn_cols:
            conn.execute("ALTER TABLE retailer_transactions ADD COLUMN budget_category_id INTEGER")
        if "budget_subcategory_id" not in txn_cols:
            conn.execute("ALTER TABLE retailer_transactions ADD COLUMN budget_subcategory_id INTEGER")
        if "retailer" not in txn_cols:
            conn.execute(
                "ALTER TABLE retailer_transactions ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'"
            )

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

        CREATE INDEX IF NOT EXISTS idx_budget_subcategories_category_id
            ON budget_subcategories(category_id);
        """
    )

    # Only create indexes on retailer_transactions if the table already exists;
    # on a fresh database schema.sql will create them after the tables are made.
    if _cols("retailer_transactions"):
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_retailer_transactions_budget_category_id
                ON retailer_transactions(budget_category_id);
            CREATE INDEX IF NOT EXISTS idx_retailer_transactions_budget_subcategory_id
                ON retailer_transactions(budget_subcategory_id);
            """
        )


def init_db(conn: sqlite3.Connection) -> None:
    _migrate_to_multi_retailer(conn)
    _ensure_columns(conn)
    schema_path = Path(__file__).parent / "sql" / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    _ensure_columns(conn)
    conn.commit()


def executemany(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> None:
    conn.executemany(sql, rows)
    conn.commit()
