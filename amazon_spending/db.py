from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_PATH = Path("data/amazon_spending.sqlite3")


@dataclass
class RetailerStatusSummary:
    retailer: str
    order_count: int
    transaction_count: int
    first_order_date: str | None
    latest_order_date: str | None
    last_import_finished_at: str | None
    last_import_status: str | None
    bound_account_label: str | None


class RetailerAccountMismatchError(RuntimeError):
    pass


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def normalize_account_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


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
        if "actual_synced_at" not in txn_cols:
            conn.execute("ALTER TABLE retailer_transactions ADD COLUMN actual_synced_at TEXT")

    cred_cols = _cols("retailer_credentials")
    if cred_cols and "cookie_jar_path" not in cred_cols:
        conn.execute("ALTER TABLE retailer_credentials ADD COLUMN cookie_jar_path TEXT")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS retailer_credentials (
            retailer TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            otp_secret TEXT,
            cookie_jar_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

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

        CREATE TABLE IF NOT EXISTS retailer_accounts (
            retailer TEXT PRIMARY KEY,
            account_key TEXT NOT NULL,
            account_label TEXT NOT NULL,
            profile_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS retailer_import_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            account_key TEXT,
            account_label TEXT,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_retailer_import_runs_retailer_finished
            ON retailer_import_runs(retailer, finished_at DESC);

        CREATE TABLE IF NOT EXISTS actual_budget_config (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            base_url TEXT NOT NULL,
            password TEXT NOT NULL,
            file TEXT NOT NULL,
            account_name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
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


def get_retailer_account(conn: sqlite3.Connection, retailer: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT retailer, account_key, account_label, profile_path, created_at, updated_at
        FROM retailer_accounts
        WHERE retailer = ?
        """,
        (retailer,),
    ).fetchone()


def recent_retailer_order_ids(
    conn: sqlite3.Connection,
    retailer: str,
    *,
    limit: int = 100,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT order_id
        FROM orders
        WHERE retailer = ?
        ORDER BY order_date DESC, created_at DESC
        LIMIT ?
        """,
        (retailer, limit),
    ).fetchall()
    return [row["order_id"] for row in rows]


def ensure_retailer_account(
    conn: sqlite3.Connection,
    retailer: str,
    account_label: str,
    *,
    account_key: str | None = None,
    profile_path: str | None = None,
) -> sqlite3.Row:
    account_label = account_label.strip()
    if not account_label:
        raise ValueError("account_label must not be empty")

    effective_key = normalize_account_key(account_key or account_label)
    existing = get_retailer_account(conn, retailer)
    if existing and existing["account_key"] != effective_key:
        raise RetailerAccountMismatchError(
            f"{retailer} is already bound to account {existing['account_label']!r}, "
            f"but the current browser session resolved to {account_label!r}. "
            "Use a different browser profile or a different database."
        )

    if existing:
        conn.execute(
            """
            UPDATE retailer_accounts
            SET account_label = ?, profile_path = COALESCE(?, profile_path), updated_at = datetime('now')
            WHERE retailer = ?
            """,
            (account_label, profile_path, retailer),
        )
    else:
        conn.execute(
            """
            INSERT INTO retailer_accounts (retailer, account_key, account_label, profile_path)
            VALUES (?, ?, ?, ?)
            """,
            (retailer, effective_key, account_label, profile_path),
        )
    conn.commit()
    row = get_retailer_account(conn, retailer)
    assert row is not None
    return row


def record_retailer_import_run(
    conn: sqlite3.Connection,
    retailer: str,
    status: str,
    notes: str,
    *,
    account_key: str | None = None,
    account_label: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO retailer_import_runs (
            retailer, status, started_at, finished_at, account_key, account_label, notes
        )
        VALUES (?, ?, datetime('now'), datetime('now'), ?, ?, ?)
        """,
        (retailer, status, account_key, account_label, notes),
    )
    conn.commit()


def summarize_retailer_status(conn: sqlite3.Connection) -> list[RetailerStatusSummary]:
    retailers = [
        row["retailer"]
        for row in conn.execute(
            """
            SELECT retailer FROM orders
            UNION
            SELECT retailer FROM retailer_transactions
            UNION
            SELECT retailer FROM retailer_accounts
            UNION
            SELECT retailer FROM retailer_import_runs
            ORDER BY retailer
            """
        ).fetchall()
    ]

    summaries: list[RetailerStatusSummary] = []
    for retailer in retailers:
        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE retailer = ?",
            (retailer,),
        ).fetchone()[0]
        transaction_count = conn.execute(
            "SELECT COUNT(*) FROM retailer_transactions WHERE retailer = ?",
            (retailer,),
        ).fetchone()[0]
        last_run = conn.execute(
            """
            SELECT finished_at, status
            FROM retailer_import_runs
            WHERE retailer = ?
            ORDER BY finished_at DESC, run_id DESC
            LIMIT 1
            """,
            (retailer,),
        ).fetchone()
        latest_activity = conn.execute(
            """
            SELECT MAX(ts) AS ts
            FROM (
                SELECT MAX(created_at) AS ts FROM orders WHERE retailer = ?
                UNION ALL
                SELECT MAX(updated_at) AS ts FROM orders WHERE retailer = ?
                UNION ALL
                SELECT MAX(created_at) AS ts FROM retailer_transactions WHERE retailer = ?
                UNION ALL
                SELECT MAX(updated_at) AS ts FROM retailer_transactions WHERE retailer = ?
            )
            """,
            (retailer, retailer, retailer, retailer),
        ).fetchone()
        order_date_range = conn.execute(
            "SELECT MIN(order_date), MAX(order_date) FROM orders WHERE retailer = ?",
            (retailer,),
        ).fetchone()
        account = get_retailer_account(conn, retailer)
        summaries.append(
            RetailerStatusSummary(
                retailer=retailer,
                order_count=order_count,
                transaction_count=transaction_count,
                first_order_date=order_date_range[0] if order_date_range else None,
                latest_order_date=order_date_range[1] if order_date_range else None,
                last_import_finished_at=(
                    last_run["finished_at"]
                    if last_run and last_run["finished_at"]
                    else latest_activity["ts"] if latest_activity else None
                ),
                last_import_status=(
                    last_run["status"]
                    if last_run
                    else "legacy_data"
                    if (latest_activity and latest_activity["ts"])
                    else None
                ),
                bound_account_label=account["account_label"] if account else None,
            )
        )
    return summaries


def get_retailer_credentials(conn: sqlite3.Connection, retailer: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT retailer, email, otp_secret, cookie_jar_path, created_at, updated_at FROM retailer_credentials WHERE retailer = ?",
        (retailer,),
    ).fetchone()


def upsert_retailer_credentials(
    conn: sqlite3.Connection,
    retailer: str,
    email: str,
    password: str,
    otp_secret: str | None = None,
    cookie_jar_path: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO retailer_credentials (retailer, email, password, otp_secret, cookie_jar_path, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(retailer) DO UPDATE SET
            email = excluded.email,
            password = excluded.password,
            otp_secret = excluded.otp_secret,
            cookie_jar_path = excluded.cookie_jar_path,
            updated_at = datetime('now')
        """,
        (retailer, email, password, otp_secret, cookie_jar_path),
    )
    conn.commit()


def get_retailer_password(conn: sqlite3.Connection, retailer: str) -> str | None:
    row = conn.execute(
        "SELECT password FROM retailer_credentials WHERE retailer = ?",
        (retailer,),
    ).fetchone()
    return row["password"] if row else None


def delete_retailer_credentials(conn: sqlite3.Connection, retailer: str) -> bool:
    cur = conn.execute("DELETE FROM retailer_credentials WHERE retailer = ?", (retailer,))
    conn.commit()
    return cur.rowcount > 0


def db_status_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    summaries = summarize_retailer_status(conn)
    return {
        "retailers": [
            {
                "retailer": summary.retailer,
                "orders": summary.order_count,
                "transactions": summary.transaction_count,
                "first_order_date": summary.first_order_date,
                "latest_order_date": summary.latest_order_date,
                "last_import_finished_at": summary.last_import_finished_at,
                "last_import_status": summary.last_import_status,
                "bound_account": summary.bound_account_label,
            }
            for summary in summaries
        ]
    }
