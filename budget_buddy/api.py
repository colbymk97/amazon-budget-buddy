from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import connect, db_status_payload, get_retailer_account, init_db, record_retailer_import_run
from .retailers import REGISTRY

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DB_PATH = PROJECT_ROOT / "data/amazon_spending.sqlite3"
DEFAULT_RAW_OUTDIR = PROJECT_ROOT / "data/raw/amazon"
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data/raw/amazon/browser_profile"

app = FastAPI(title="Budget Buddy API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SYNC_LOCK = threading.Lock()
_SYNC_STATE: dict[str, Any] = {
    "running": False,
    "cancel_requested": False,
    "progress": 0,
    "stage": "idle",
    "started_at": None,
    "finished_at": None,
    "last_order_date": None,
    "last_transaction_date": None,
    "new_transactions_added": 0,
    "new_orders_added": 0,
    "sync_since_date": None,
    "status": "idle",
    "notes": "",
    "error": None,
}


class TransactionBudgetUpdate(BaseModel):
    budget_category_id: Optional[int] = None
    budget_subcategory_id: Optional[int] = None


def _rows_to_dict(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _construct_order_url(order_id: str, order_url: str | None) -> str:
    if order_url:
        return order_url
    return f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"


def _decorate_budget_fields(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if "budget_category_name" not in data:
        data["budget_category_name"] = None
    if "budget_subcategory_name" not in data:
        data["budget_subcategory_name"] = None
    return data


def _load_transaction_with_budget(conn, retailer_txn_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            rt.retailer_txn_id,
            rt.retailer,
            rt.order_id,
            o.order_date,
            o.order_url,
            o.order_total_cents,
            o.tax_cents,
            rt.txn_date,
            rt.amount_cents,
            rt.payment_last4,
            rt.raw_label,
            rt.source_url,
            rt.budget_category_id,
            rt.budget_subcategory_id,
            bc.name AS budget_category_name,
            bsc.name AS budget_subcategory_name
        FROM retailer_transactions rt
        LEFT JOIN orders o ON o.order_id = rt.order_id
        LEFT JOIN budget_categories bc ON bc.category_id = rt.budget_category_id
        LEFT JOIN budget_subcategories bsc ON bsc.subcategory_id = rt.budget_subcategory_id
        WHERE rt.retailer_txn_id = ?
        """,
        (retailer_txn_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    data = _decorate_budget_fields(row)
    data["order_url"] = _construct_order_url(data["order_id"], data.get("order_url"))
    return data


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_dates(conn) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        SELECT
            (SELECT MAX(order_date) FROM orders) AS last_order_date,
            (SELECT MAX(txn_date) FROM retailer_transactions) AS last_transaction_date
        """
    ).fetchone()
    return row["last_order_date"], row["last_transaction_date"]


def _recent_order_ids(conn, limit: int = 30) -> list[str]:
    rows = conn.execute(
        """
        SELECT order_id
        FROM orders
        WHERE order_date IS NOT NULL
        ORDER BY order_date DESC, order_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row["order_id"] for row in rows]


def _incremental_start_date(last_order_date: str | None, overlap_days: int = 2) -> str | None:
    if not last_order_date:
        return None
    try:
        d = datetime.strptime(last_order_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (d - timedelta(days=max(0, overlap_days))).isoformat()


def _incremental_max_pages(
    last_order_date: str | None,
    overlap_days: int = 2,
    orders_per_day_estimate: int = 4,
    min_pages: int = 2,
    max_pages: int = 16,
) -> int:
    if not last_order_date:
        return max_pages
    try:
        last = datetime.strptime(last_order_date, "%Y-%m-%d").date()
    except ValueError:
        return max_pages

    today = datetime.now(timezone.utc).date()
    days_since = max(1, (today - last).days + max(0, overlap_days))
    estimated_orders = max(1, days_since * max(1, orders_per_day_estimate))
    pages = ((estimated_orders + 9) // 10) + 1
    return max(min_pages, min(max_pages, pages))


def _should_retry_headed(result) -> bool:
    if getattr(result, "status", None) == "auth_required":
        return True
    return (
        getattr(result, "status", None) == "no_data"
        and int(getattr(result, "orders_collected", 0) or 0) == 0
        and int(getattr(result, "discovered_orders", 0) or 0) == 0
    )


def _sync_completion_note(since_date: str | None, new_orders: int, new_txns: int) -> str:
    since_label = since_date or "your last import"
    if new_orders <= 0 and new_txns <= 0:
        return f"No new orders found since {since_label}."
    return (
        f"Import complete. Found {new_orders} order(s) since {since_label} "
        f"and added {new_txns} new transaction(s)."
    )


def _sync_snapshot() -> dict[str, Any]:
    with _SYNC_LOCK:
        return dict(_SYNC_STATE)


def _set_sync_state(**kwargs) -> None:
    with _SYNC_LOCK:
        _SYNC_STATE.update(kwargs)


def _cancel_requested() -> bool:
    with _SYNC_LOCK:
        return bool(_SYNC_STATE.get("cancel_requested"))


def _record_sync_run(status: str, notes: str) -> None:
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        bound_account = get_retailer_account(conn, "amazon")
        record_retailer_import_run(
            conn,
            "amazon",
            status,
            notes,
            account_key=bound_account["account_key"] if bound_account else None,
            account_label=bound_account["account_label"] if bound_account else None,
        )
    finally:
        conn.close()


def _run_sync_job() -> None:
    _set_sync_state(
        running=True,
        cancel_requested=False,
        progress=5,
        stage="starting",
        started_at=_utcnow_iso(),
        finished_at=None,
        status="running",
        notes="Starting background import...",
        error=None,
        new_transactions_added=0,
        new_orders_added=0,
        sync_since_date=None,
    )
    try:
        conn_before = connect(DEFAULT_API_DB_PATH)
        try:
            before_order_date, before_txn_date = _latest_dates(conn_before)
            recent_known_order_ids = _recent_order_ids(conn_before, limit=30)
        finally:
            conn_before.close()
        _set_sync_state(
            progress=15,
            stage="collecting",
            last_order_date=before_order_date,
            last_transaction_date=before_txn_date,
            sync_since_date=before_order_date,
            notes="Collecting latest orders and transactions...",
        )
        sync_start_date = _incremental_start_date(before_order_date, overlap_days=2)
        sync_max_pages = _incremental_max_pages(before_order_date, overlap_days=2)
        if recent_known_order_ids:
            sync_max_pages = max(sync_max_pages, 40)
        _set_sync_state(
            notes=(
                "Collecting latest orders and transactions "
                f"(since={before_order_date or 'full import'}, "
                f"start_date={sync_start_date or 'none'}, max_pages_cap={sync_max_pages})..."
            )
        )

        conn = connect(DEFAULT_API_DB_PATH)
        try:
            result = REGISTRY["amazon"].collect(
                conn=conn,
                output_dir=DEFAULT_RAW_OUTDIR,
                start_date=sync_start_date,
                max_pages=sync_max_pages,
                headless=True,
                user_data_dir=DEFAULT_PROFILE_DIR,
                allow_interactive_auth=False,
                should_abort=_cancel_requested,
                stop_when_before_start_date=True,
                known_order_ids=recent_known_order_ids,
                overlap_match_threshold=2,
                save_raw="on-error",
                raw_retention_runs=10,
            )
        finally:
            conn.close()

        # Some sessions are valid but Amazon still challenges headless mode.
        # Retry once headed (non-interactive) using the same persistent profile.
        if _should_retry_headed(result):
            _set_sync_state(
                progress=35,
                stage="retry_headed",
                notes="Headless scrape returned no usable data. Retrying in a visible browser window...",
            )
            conn_retry = connect(DEFAULT_API_DB_PATH)
            try:
                result = REGISTRY["amazon"].collect(
                    conn=conn_retry,
                    output_dir=DEFAULT_RAW_OUTDIR,
                    start_date=sync_start_date,
                    max_pages=sync_max_pages,
                    headless=False,
                    user_data_dir=DEFAULT_PROFILE_DIR,
                    allow_interactive_auth=False,
                    should_abort=_cancel_requested,
                    stop_when_before_start_date=True,
                    known_order_ids=recent_known_order_ids,
                    overlap_match_threshold=2,
                    save_raw="on-error",
                    raw_retention_runs=10,
                )
            finally:
                conn_retry.close()

        if result.status == "cancelled":
            _record_sync_run("cancelled", "Import terminated by user.")
            _set_sync_state(
                running=False,
                cancel_requested=False,
                progress=100,
                stage="cancelled",
                finished_at=_utcnow_iso(),
                status="cancelled",
                notes="Import terminated by user.",
                error=None,
                new_transactions_added=0,
                new_orders_added=0,
            )
            return

        _set_sync_state(progress=90, stage="finalizing", notes="Finalizing import and computing deltas...")
        conn_after = connect(DEFAULT_API_DB_PATH)
        try:
            after_order_date, after_txn_date = _latest_dates(conn_after)
        finally:
            conn_after.close()

        new_txns = int(getattr(result, "amazon_txns_inserted", 0) or 0)  # field name kept for compat
        new_orders = int(getattr(result, "orders_inserted", 0) or 0)
        notes = _sync_completion_note(before_order_date, new_orders, new_txns)

        _record_sync_run(result.status, notes if result.status == "ok" else result.notes)

        _set_sync_state(
            running=False,
            cancel_requested=False,
            progress=100,
            stage="complete",
            finished_at=_utcnow_iso(),
            status=result.status,
            notes=notes if result.status == "ok" else result.notes,
            error=None if result.status == "ok" else result.notes,
            last_order_date=after_order_date,
            last_transaction_date=after_txn_date,
            new_transactions_added=new_txns,
            new_orders_added=new_orders,
        )
    except Exception as exc:
        _record_sync_run("error", f"Background import failed: {exc}")
        _set_sync_state(
            running=False,
            cancel_requested=False,
            progress=100,
            stage="error",
            finished_at=_utcnow_iso(),
            status="error",
            notes="Background import failed.",
            error=str(exc),
            new_orders_added=0,
        )


def _ensure_api_db_schema() -> None:
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        init_db(conn)
    finally:
        conn.close()


_ensure_api_db_schema()


@app.get("/sync/status")
def sync_status():
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        last_order_date, last_txn_date = _latest_dates(conn)
    finally:
        conn.close()
    snap = _sync_snapshot()
    if not snap.get("running"):
        snap["last_order_date"] = last_order_date
        snap["last_transaction_date"] = last_txn_date
    return snap


@app.get("/status/retailers")
def status_retailers():
    """Per-retailer sync/import status: order counts, date ranges, last import result."""
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        return db_status_payload(conn)
    finally:
        conn.close()


@app.post("/sync/start")
def sync_start():
    snap = _sync_snapshot()
    if snap.get("running"):
        return {"started": False, "message": "Sync already running.", "status": snap}
    t = threading.Thread(target=_run_sync_job, daemon=True)
    t.start()
    return {"started": True, "message": "Sync started."}


@app.post("/sync/cancel")
def sync_cancel():
    snap = _sync_snapshot()
    if not snap.get("running"):
        return {"cancelled": False, "message": "No sync running."}
    _set_sync_state(
        cancel_requested=True,
        stage="cancelling",
        notes="Cancellation requested. Stopping import...",
    )
    return {"cancelled": True, "message": "Cancellation requested."}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/budget/categories")
def list_budget_categories():
    """Read-only mirror of Actual's category groups. Refresh via POST /actual/categories/sync."""
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                bc.category_id,
                bc.actual_group_id,
                bc.name,
                bc.description,
                COUNT(bsc.subcategory_id) AS subcategory_count
            FROM budget_categories bc
            LEFT JOIN budget_subcategories bsc ON bsc.category_id = bc.category_id
            GROUP BY bc.category_id, bc.actual_group_id, bc.name, bc.description
            ORDER BY bc.name
            """
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.get("/budget/subcategories")
def list_budget_subcategories(category_id: Optional[int] = Query(default=None)):
    """Read-only mirror of Actual's categories. Refresh via POST /actual/categories/sync."""
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        params: tuple[Any, ...] = ()
        where = ""
        if category_id is not None:
            where = "WHERE bsc.category_id = ?"
            params = (category_id,)
        rows = conn.execute(
            f"""
            SELECT
                bsc.subcategory_id,
                bsc.category_id,
                bsc.actual_category_id,
                bc.name AS category_name,
                bsc.name,
                bsc.description
            FROM budget_subcategories bsc
            JOIN budget_categories bc ON bc.category_id = bsc.category_id
            {where}
            ORDER BY bc.name, bsc.name
            """,
            params,
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.patch("/transactions/{retailer_txn_id}/budget")
def assign_transaction_budget(retailer_txn_id: str, payload: TransactionBudgetUpdate):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        txn = conn.execute(
            "SELECT retailer_txn_id FROM retailer_transactions WHERE retailer_txn_id = ?",
            (retailer_txn_id,),
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")

        category_id = payload.budget_category_id
        subcategory_id = payload.budget_subcategory_id

        if subcategory_id is not None:
            subcategory = conn.execute(
                "SELECT subcategory_id, category_id FROM budget_subcategories WHERE subcategory_id = ?",
                (subcategory_id,),
            ).fetchone()
            if not subcategory:
                raise HTTPException(status_code=404, detail="Subcategory not found")
            subcategory_category_id = subcategory["category_id"]
            if category_id is not None and category_id != subcategory_category_id:
                raise HTTPException(
                    status_code=400,
                    detail="Subcategory does not belong to selected category",
                )
            category_id = subcategory_category_id

        if category_id is not None:
            category = conn.execute(
                "SELECT category_id FROM budget_categories WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")

        conn.execute(
            """
            UPDATE retailer_transactions
            SET budget_category_id = ?, budget_subcategory_id = ?, updated_at = datetime('now')
            WHERE retailer_txn_id = ?
            """,
            (category_id, subcategory_id, retailer_txn_id),
        )
        conn.commit()
        return _load_transaction_with_budget(conn, retailer_txn_id)
    finally:
        conn.close()


@app.get("/orders")
def list_orders(
    search: str = Query(default=""),
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        like = f"%{search.strip()}%"
        rows = conn.execute(
            """
            SELECT
                o.order_id,
                o.retailer,
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                o.shipping_cents,
                o.payment_last4,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT at.retailer_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN retailer_transactions at ON at.order_id = o.order_id
            WHERE o.order_date >= ? AND o.order_date <= ?
              AND (
                o.order_id LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM order_items oi2
                    WHERE oi2.order_id = o.order_id AND oi2.title LIKE ?
                )
              )
            GROUP BY o.order_id, o.retailer, o.order_date, o.order_url, o.order_total_cents, o.tax_cents, o.shipping_cents, o.payment_last4
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT ? OFFSET ?
            """,
            (start_date, end_date, like, like, limit, offset),
        ).fetchall()
        data = _rows_to_dict(rows)
        for r in data:
            r["order_url"] = _construct_order_url(r["order_id"], r.get("order_url"))
        return {"rows": data}
    finally:
        conn.close()


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT
                o.order_id,
                o.retailer,
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                o.shipping_cents,
                o.payment_last4,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT at.retailer_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN retailer_transactions at ON at.order_id = o.order_id
            WHERE o.order_id = ?
            GROUP BY o.order_id, o.retailer, o.order_date, o.order_url, o.order_total_cents, o.tax_cents, o.shipping_cents, o.payment_last4
            """,
            (order_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        data = dict(row)
        data["order_url"] = _construct_order_url(data["order_id"], data.get("order_url"))
        return data
    finally:
        conn.close()


@app.get("/orders/{order_id}/transactions")
def order_transactions(order_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                retailer_txn_id,
                retailer,
                order_id,
                txn_date,
                amount_cents,
                payment_last4,
                raw_label,
                source_url,
                budget_category_id,
                budget_subcategory_id
            FROM retailer_transactions
            WHERE order_id = ?
            ORDER BY COALESCE(txn_date, '0000-00-00') DESC, retailer_txn_id
            """,
            (order_id,),
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.get("/orders/{order_id}/items")
def order_items(order_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                item_id,
                order_id,
                title,
                quantity,
                item_subtotal_cents,
                item_tax_cents,
                retailer_transaction_id
            FROM order_items
            WHERE order_id = ?
            ORDER BY item_id
            """,
            (order_id,),
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.get("/transactions")
def list_transactions(
    search: str = Query(default=""),
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        like = f"%{search.strip()}%"
        rows = conn.execute(
            """
            SELECT
                at.retailer_txn_id,
                at.retailer,
                at.order_id,
                o.order_date,
                o.order_url,
                at.txn_date,
                at.amount_cents,
                at.payment_last4,
                at.raw_label,
                at.source_url,
                at.budget_category_id,
                at.budget_subcategory_id,
                bc.name AS budget_category_name,
                bsc.name AS budget_subcategory_name
            FROM retailer_transactions at
            LEFT JOIN orders o ON o.order_id = at.order_id
            LEFT JOIN budget_categories bc ON bc.category_id = at.budget_category_id
            LEFT JOIN budget_subcategories bsc ON bsc.subcategory_id = at.budget_subcategory_id
            WHERE COALESCE(at.txn_date, o.order_date, '0000-00-00') >= ?
              AND COALESCE(at.txn_date, o.order_date, '9999-12-31') <= ?
              AND (
                at.retailer_txn_id LIKE ?
                OR at.order_id LIKE ?
                OR COALESCE(at.raw_label, '') LIKE ?
              )
            ORDER BY COALESCE(at.txn_date, o.order_date, '0000-00-00') DESC, at.retailer_txn_id DESC
            LIMIT ? OFFSET ?
            """,
            (start_date, end_date, like, like, like, limit, offset),
        ).fetchall()
        data = [_decorate_budget_fields(r) for r in rows]
        for r in data:
            r["order_url"] = _construct_order_url(r["order_id"], r.get("order_url"))
        return {"rows": data}
    finally:
        conn.close()


@app.get("/transactions/{retailer_txn_id}")
def get_transaction(retailer_txn_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        return _load_transaction_with_budget(conn, retailer_txn_id)
    finally:
        conn.close()


@app.get("/transactions/{retailer_txn_id}/items")
def transaction_items(retailer_txn_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                oi.item_id,
                oi.order_id,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents,
                oi.item_tax_cents,
                oit.allocated_amount_cents,
                oit.method
            FROM order_item_transactions oit
            JOIN order_items oi ON oi.item_id = oit.item_id
            WHERE oit.retailer_txn_id = ?
            ORDER BY oi.item_id
            """,
            (retailer_txn_id,),
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.get("/items")
def list_items(
    search: str = Query(default=""),
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        like = f"%{search.strip()}%"
        rows = conn.execute(
            """
            SELECT
                oi.item_id,
                oi.order_id,
                o.retailer,
                o.order_date,
                o.order_url,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents,
                oi.item_tax_cents,
                oi.retailer_transaction_id
            FROM order_items oi
            LEFT JOIN orders o ON o.order_id = oi.order_id
            WHERE COALESCE(o.order_date, '0000-00-00') >= ?
              AND COALESCE(o.order_date, '9999-12-31') <= ?
              AND (
                oi.item_id LIKE ?
                OR oi.order_id LIKE ?
                OR COALESCE(oi.title, '') LIKE ?
              )
            ORDER BY COALESCE(o.order_date, '0000-00-00') DESC, oi.order_id DESC, oi.item_id ASC
            LIMIT ? OFFSET ?
            """,
            (start_date, end_date, like, like, like, limit, offset),
        ).fetchall()
        data = _rows_to_dict(rows)
        for r in data:
            r["order_url"] = _construct_order_url(r["order_id"], r.get("order_url"))
        return {"rows": data}
    finally:
        conn.close()


@app.get("/items/{item_id}")
def get_item(item_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT
                oi.item_id,
                oi.order_id,
                o.retailer,
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents,
                oi.item_tax_cents,
                oi.retailer_transaction_id
            FROM order_items oi
            LEFT JOIN orders o ON o.order_id = oi.order_id
            WHERE oi.item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        data = dict(row)
        data["order_url"] = _construct_order_url(data["order_id"], data.get("order_url"))
        return data
    finally:
        conn.close()


@app.get("/items/{item_id}/transactions")
def item_transactions(item_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                at.retailer_txn_id,
                at.retailer,
                at.order_id,
                at.txn_date,
                at.amount_cents,
                at.raw_label,
                at.budget_category_id,
                at.budget_subcategory_id,
                oit.allocated_amount_cents,
                oit.method
            FROM order_item_transactions oit
            JOIN retailer_transactions at ON at.retailer_txn_id = oit.retailer_txn_id
            WHERE oit.item_id = ?
            ORDER BY COALESCE(at.txn_date, '0000-00-00') DESC, at.retailer_txn_id
            """,
            (item_id,),
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.get("/reports/spend-by-month")
def reports_spend_by_month(
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        order_rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', order_date) AS month,
                retailer,
                COUNT(*) AS order_count,
                SUM(order_total_cents) AS gross_order_cents
            FROM orders
            WHERE order_date >= ? AND order_date <= ?
            GROUP BY month, retailer
            """,
            (start_date, end_date),
        ).fetchall()
        txn_rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', COALESCE(rt.txn_date, o.order_date)) AS month,
                rt.retailer AS retailer,
                COUNT(*) AS txn_count,
                SUM(rt.amount_cents) AS net_amount_cents
            FROM retailer_transactions rt
            LEFT JOIN orders o ON o.order_id = rt.order_id
            WHERE COALESCE(rt.txn_date, o.order_date) >= ? AND COALESCE(rt.txn_date, o.order_date) <= ?
            GROUP BY month, rt.retailer
            """,
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    months: dict[str, dict[str, Any]] = {}
    retailers: set[str] = set()

    def _month_entry(month: str) -> dict[str, Any]:
        return months.setdefault(
            month,
            {
                "month": month,
                "order_count": 0,
                "gross_order_cents": 0,
                "txn_count": 0,
                "net_amount_cents": 0,
                "by_retailer": {},
            },
        )

    def _retailer_entry(entry: dict[str, Any], retailer: str) -> dict[str, Any]:
        return entry["by_retailer"].setdefault(
            retailer,
            {"order_count": 0, "gross_order_cents": 0, "txn_count": 0, "net_amount_cents": 0},
        )

    for row in order_rows:
        if not row["month"]:
            continue
        retailer = row["retailer"] or "unknown"
        retailers.add(retailer)
        entry = _month_entry(row["month"])
        entry["order_count"] += row["order_count"] or 0
        entry["gross_order_cents"] += row["gross_order_cents"] or 0
        r_entry = _retailer_entry(entry, retailer)
        r_entry["order_count"] += row["order_count"] or 0
        r_entry["gross_order_cents"] += row["gross_order_cents"] or 0

    for row in txn_rows:
        if not row["month"]:
            continue
        retailer = row["retailer"] or "unknown"
        retailers.add(retailer)
        entry = _month_entry(row["month"])
        entry["txn_count"] += row["txn_count"] or 0
        entry["net_amount_cents"] += row["net_amount_cents"] or 0
        r_entry = _retailer_entry(entry, retailer)
        r_entry["txn_count"] += row["txn_count"] or 0
        r_entry["net_amount_cents"] += row["net_amount_cents"] or 0

    ordered_months = [months[m] for m in sorted(months.keys())]
    return {
        "start_date": start_date,
        "end_date": end_date,
        "retailers": sorted(retailers),
        "months": ordered_months,
    }


@app.get("/reports/spend-by-retailer")
def reports_spend_by_retailer(
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        order_rows = conn.execute(
            """
            SELECT
                retailer,
                COUNT(*) AS order_count,
                SUM(order_total_cents) AS gross_order_cents,
                MIN(order_date) AS first_order_date,
                MAX(order_date) AS latest_order_date
            FROM orders
            WHERE order_date >= ? AND order_date <= ?
            GROUP BY retailer
            """,
            (start_date, end_date),
        ).fetchall()
        txn_rows = conn.execute(
            """
            SELECT
                rt.retailer AS retailer,
                COUNT(*) AS txn_count,
                SUM(rt.amount_cents) AS net_amount_cents
            FROM retailer_transactions rt
            LEFT JOIN orders o ON o.order_id = rt.order_id
            WHERE COALESCE(rt.txn_date, o.order_date) >= ? AND COALESCE(rt.txn_date, o.order_date) <= ?
            GROUP BY rt.retailer
            """,
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    by_retailer: dict[str, dict[str, Any]] = {}
    for row in order_rows:
        retailer = row["retailer"] or "unknown"
        by_retailer[retailer] = {
            "retailer": retailer,
            "order_count": row["order_count"] or 0,
            "gross_order_cents": row["gross_order_cents"] or 0,
            "first_order_date": row["first_order_date"],
            "latest_order_date": row["latest_order_date"],
            "txn_count": 0,
            "net_amount_cents": 0,
        }
    for row in txn_rows:
        retailer = row["retailer"] or "unknown"
        entry = by_retailer.setdefault(
            retailer,
            {
                "retailer": retailer,
                "order_count": 0,
                "gross_order_cents": 0,
                "first_order_date": None,
                "latest_order_date": None,
                "txn_count": 0,
                "net_amount_cents": 0,
            },
        )
        entry["txn_count"] = row["txn_count"] or 0
        entry["net_amount_cents"] = row["net_amount_cents"] or 0

    return {
        "start_date": start_date,
        "end_date": end_date,
        "retailers": sorted(by_retailer.values(), key=lambda r: r["retailer"]),
    }


@app.get("/reports/spend-by-category")
def reports_spend_by_category(
    start_date: str = Query(default="2000-01-01"),
    end_date: str = Query(default="2100-01-01"),
    category_id: Optional[int] = Query(default=None),
):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        if category_id is None:
            rows = conn.execute(
                """
                SELECT
                    bc.category_id AS id,
                    COALESCE(bc.name, 'Uncategorized') AS name,
                    COUNT(*) AS txn_count,
                    SUM(rt.amount_cents) AS net_amount_cents
                FROM retailer_transactions rt
                LEFT JOIN orders o ON o.order_id = rt.order_id
                LEFT JOIN budget_categories bc ON bc.category_id = rt.budget_category_id
                WHERE COALESCE(rt.txn_date, o.order_date) >= ? AND COALESCE(rt.txn_date, o.order_date) <= ?
                GROUP BY bc.category_id, bc.name
                ORDER BY net_amount_cents ASC
                """,
                (start_date, end_date),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    bsc.subcategory_id AS id,
                    COALESCE(bsc.name, 'Uncategorized') AS name,
                    COUNT(*) AS txn_count,
                    SUM(rt.amount_cents) AS net_amount_cents
                FROM retailer_transactions rt
                LEFT JOIN orders o ON o.order_id = rt.order_id
                LEFT JOIN budget_subcategories bsc ON bsc.subcategory_id = rt.budget_subcategory_id
                WHERE COALESCE(rt.txn_date, o.order_date) >= ? AND COALESCE(rt.txn_date, o.order_date) <= ?
                  AND rt.budget_category_id = ?
                GROUP BY bsc.subcategory_id, bsc.name
                ORDER BY net_amount_cents ASC
                """,
                (start_date, end_date, category_id),
            ).fetchall()
    finally:
        conn.close()

    return {
        "start_date": start_date,
        "end_date": end_date,
        "category_id": category_id,
        "rows": _rows_to_dict(rows),
    }


# ---------------------------------------------------------------------------
# Actual Budget integration
# ---------------------------------------------------------------------------

@app.get("/actual/status")
def actual_status():
    """Return Actual Budget configuration status plus a read-only sync breakdown.

    The synced/skipped/pending/incomplete counts and skip-reason breakdown are
    computed from local columns and returned even when Actual isn't configured.
    """
    from .actual_sync import load_config

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        cfg = load_config(conn)
        summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_transactions,
                SUM(CASE WHEN actual_synced_at IS NOT NULL THEN 1 ELSE 0 END) AS synced,
                SUM(CASE WHEN actual_synced_at IS NULL AND actual_skipped_at IS NOT NULL
                         THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN actual_synced_at IS NULL AND actual_skipped_at IS NULL
                         AND txn_date IS NOT NULL AND amount_cents IS NOT NULL
                         THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN txn_date IS NULL OR amount_cents IS NULL THEN 1 ELSE 0 END) AS incomplete,
                MAX(actual_synced_at) AS last_synced_at
            FROM retailer_transactions
            """
        ).fetchone()
        skip_reason_rows = conn.execute(
            """
            SELECT actual_skip_reason AS reason, COUNT(*) AS count
            FROM retailer_transactions
            WHERE actual_synced_at IS NULL AND actual_skipped_at IS NOT NULL
            GROUP BY actual_skip_reason
            ORDER BY count DESC
            """
        ).fetchall()
    finally:
        conn.close()

    payload = {
        "configured": cfg is not None,
        "base_url": cfg.base_url if cfg else None,
        "file": cfg.file if cfg else None,
        "account_name": cfg.account_name if cfg else None,
        "pending": summary_row["pending"] or 0,
        "total_transactions": summary_row["total_transactions"] or 0,
        "synced": summary_row["synced"] or 0,
        "skipped": summary_row["skipped"] or 0,
        "incomplete": summary_row["incomplete"] or 0,
        "last_synced_at": summary_row["last_synced_at"],
        "skip_reasons": _rows_to_dict(skip_reason_rows),
    }
    return payload


@app.post("/actual/sync")
def actual_sync(dry_run: bool = Query(False)):
    """Push unsynced retailer transactions to Actual Budget.

    Each matched transaction has its notes updated with the Amazon order ID
    and the line-items allocated to it. Transactions are only synced once;
    already-synced rows are skipped.

    Pass ``?dry_run=true`` to preview matches without writing any changes.
    """
    from .actual_sync import load_config, sync_to_actual

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        cfg = load_config(conn)
        if not cfg:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Actual Budget is not configured. "
                    "Run the actual-configure CLI command first."
                ),
            )
        result = sync_to_actual(conn, cfg, dry_run=dry_run)
    finally:
        conn.close()
    return {"dry_run": dry_run, **result.to_dict()}


@app.post("/actual/categories/sync")
def actual_categories_sync():
    """Refresh the local category-group/category mirror from Actual.

    Read-only against Actual — never creates or edits categories there.
    """
    from .actual_sync import load_config, sync_categories_from_actual

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        cfg = load_config(conn)
        if not cfg:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Actual Budget is not configured. "
                    "Run the actual-configure CLI command first."
                ),
            )
        count = sync_categories_from_actual(conn, cfg)
    finally:
        conn.close()
    return {"categories_synced": count}
