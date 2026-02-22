from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .collector import collect_amazon
from .db import connect, init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DB_PATH = PROJECT_ROOT / "data/amazon_spending.sqlite3"
DEFAULT_RAW_OUTDIR = PROJECT_ROOT / "data/raw/amazon"
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data/raw/amazon/browser_profile"

app = FastAPI(title="Amazon Spending API", version="0.1.0")
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
    "status": "idle",
    "notes": "",
    "error": None,
}


class BudgetCategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None


class BudgetSubcategoryCreate(BaseModel):
    category_id: int
    name: str
    description: Optional[str] = None


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


def _load_transaction_with_budget(conn, amazon_txn_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            at.amazon_txn_id,
            at.order_id,
            o.order_date,
            o.order_url,
            o.order_total_cents,
            o.tax_cents,
            at.txn_date,
            at.amount_cents,
            at.payment_last4,
            at.raw_label,
            at.source_url,
            at.budget_category_id,
            at.budget_subcategory_id,
            bc.name AS budget_category_name,
            bsc.name AS budget_subcategory_name
        FROM amazon_transactions at
        LEFT JOIN orders o ON o.order_id = at.order_id
        LEFT JOIN budget_categories bc ON bc.category_id = at.budget_category_id
        LEFT JOIN budget_subcategories bsc ON bsc.subcategory_id = at.budget_subcategory_id
        WHERE at.amazon_txn_id = ?
        """,
        (amazon_txn_id,),
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
            (SELECT MAX(txn_date) FROM amazon_transactions) AS last_transaction_date
        """
    ).fetchone()
    return row["last_order_date"], row["last_transaction_date"]


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


def _sync_snapshot() -> dict[str, Any]:
    with _SYNC_LOCK:
        return dict(_SYNC_STATE)


def _set_sync_state(**kwargs) -> None:
    with _SYNC_LOCK:
        _SYNC_STATE.update(kwargs)


def _cancel_requested() -> bool:
    with _SYNC_LOCK:
        return bool(_SYNC_STATE.get("cancel_requested"))


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
    )
    try:
        conn_before = connect(DEFAULT_API_DB_PATH)
        try:
            before_order_date, before_txn_date = _latest_dates(conn_before)
        finally:
            conn_before.close()
        _set_sync_state(
            progress=15,
            stage="collecting",
            last_order_date=before_order_date,
            last_transaction_date=before_txn_date,
            notes="Collecting latest orders and transactions...",
        )
        sync_start_date = _incremental_start_date(before_order_date, overlap_days=2)
        sync_max_pages = _incremental_max_pages(before_order_date, overlap_days=2)
        _set_sync_state(
            notes=(
                "Collecting latest orders and transactions "
                f"(start_date={sync_start_date or 'none'}, max_pages={sync_max_pages})..."
            )
        )

        conn = connect(DEFAULT_API_DB_PATH)
        try:
            result = collect_amazon(
                conn=conn,
                output_dir=DEFAULT_RAW_OUTDIR,
                start_date=sync_start_date,
                max_pages=sync_max_pages,
                headless=True,
                user_data_dir=DEFAULT_PROFILE_DIR,
                allow_interactive_auth=False,
                should_abort=_cancel_requested,
                stop_when_before_start_date=True,
            )
        finally:
            conn.close()

        # Some sessions are valid but Amazon still challenges headless mode.
        # Retry once headed (non-interactive) using the same persistent profile.
        if result.status == "auth_required":
            _set_sync_state(
                progress=35,
                stage="retry_headed",
                notes="Headless auth challenge detected. Retrying headed mode with existing session...",
            )
            conn_retry = connect(DEFAULT_API_DB_PATH)
            try:
                result = collect_amazon(
                    conn=conn_retry,
                    output_dir=DEFAULT_RAW_OUTDIR,
                    start_date=sync_start_date,
                    max_pages=sync_max_pages,
                    headless=False,
                    user_data_dir=DEFAULT_PROFILE_DIR,
                    allow_interactive_auth=False,
                    should_abort=_cancel_requested,
                    stop_when_before_start_date=True,
                )
            finally:
                conn_retry.close()

        if result.status == "cancelled":
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
            )
            return

        _set_sync_state(progress=90, stage="finalizing", notes="Finalizing import and computing deltas...")
        conn_after = connect(DEFAULT_API_DB_PATH)
        try:
            after_order_date, after_txn_date = _latest_dates(conn_after)
        finally:
            conn_after.close()

        new_txns = int(getattr(result, "amazon_txns_inserted", 0) or 0)
        if new_txns == 0 and result.status == "ok":
            notes = "No new transactions found since your last import."
        else:
            notes = f"Import complete. Added {new_txns} new transaction(s)."

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
        )
    except Exception as exc:
        _set_sync_state(
            running=False,
            cancel_requested=False,
            progress=100,
            stage="error",
            finished_at=_utcnow_iso(),
            status="error",
            notes="Background import failed.",
            error=str(exc),
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
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                bc.category_id,
                bc.name,
                bc.description,
                COUNT(bsc.subcategory_id) AS subcategory_count
            FROM budget_categories bc
            LEFT JOIN budget_subcategories bsc ON bsc.category_id = bc.category_id
            GROUP BY bc.category_id, bc.name, bc.description
            ORDER BY bc.name
            """
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()


@app.post("/budget/categories")
def create_budget_category(payload: BudgetCategoryCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        try:
            cur = conn.execute(
                """
                INSERT INTO budget_categories (name, description, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                (name, payload.description),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Category already exists")
        row = conn.execute(
            "SELECT category_id, name, description FROM budget_categories WHERE category_id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


@app.get("/budget/subcategories")
def list_budget_subcategories(category_id: Optional[int] = Query(default=None)):
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


@app.post("/budget/subcategories")
def create_budget_subcategory(payload: BudgetSubcategoryCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Subcategory name is required")
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        category = conn.execute(
            "SELECT category_id FROM budget_categories WHERE category_id = ?",
            (payload.category_id,),
        ).fetchone()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        try:
            cur = conn.execute(
                """
                INSERT INTO budget_subcategories (category_id, name, description, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (payload.category_id, name, payload.description),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Subcategory already exists in category")
        row = conn.execute(
            """
            SELECT subcategory_id, category_id, name, description
            FROM budget_subcategories
            WHERE subcategory_id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


@app.patch("/transactions/{amazon_txn_id}/budget")
def assign_transaction_budget(amazon_txn_id: str, payload: TransactionBudgetUpdate):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        txn = conn.execute(
            "SELECT amazon_txn_id FROM amazon_transactions WHERE amazon_txn_id = ?",
            (amazon_txn_id,),
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
            UPDATE amazon_transactions
            SET budget_category_id = ?, budget_subcategory_id = ?, updated_at = datetime('now')
            WHERE amazon_txn_id = ?
            """,
            (category_id, subcategory_id, amazon_txn_id),
        )
        conn.commit()
        return _load_transaction_with_budget(conn, amazon_txn_id)
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
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                o.shipping_cents,
                o.payment_last4,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT at.amazon_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN amazon_transactions at ON at.order_id = o.order_id
            WHERE o.order_date >= ? AND o.order_date <= ?
              AND (
                o.order_id LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM order_items oi2
                    WHERE oi2.order_id = o.order_id AND oi2.title LIKE ?
                )
              )
            GROUP BY o.order_id, o.order_date, o.order_url, o.order_total_cents, o.tax_cents, o.shipping_cents, o.payment_last4
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
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                o.shipping_cents,
                o.payment_last4,
                COUNT(DISTINCT oi.item_id) AS item_count,
                COUNT(DISTINCT at.amazon_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN amazon_transactions at ON at.order_id = o.order_id
            WHERE o.order_id = ?
            GROUP BY o.order_id, o.order_date, o.order_url, o.order_total_cents, o.tax_cents, o.shipping_cents, o.payment_last4
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
                amazon_txn_id,
                order_id,
                txn_date,
                amount_cents,
                payment_last4,
                raw_label,
                source_url,
                budget_category_id,
                budget_subcategory_id
            FROM amazon_transactions
            WHERE order_id = ?
            ORDER BY COALESCE(txn_date, '0000-00-00') DESC, amazon_txn_id
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
                amazon_transaction_id
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
                at.amazon_txn_id,
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
            FROM amazon_transactions at
            LEFT JOIN orders o ON o.order_id = at.order_id
            LEFT JOIN budget_categories bc ON bc.category_id = at.budget_category_id
            LEFT JOIN budget_subcategories bsc ON bsc.subcategory_id = at.budget_subcategory_id
            WHERE COALESCE(at.txn_date, o.order_date, '0000-00-00') >= ?
              AND COALESCE(at.txn_date, o.order_date, '9999-12-31') <= ?
              AND (
                at.amazon_txn_id LIKE ?
                OR at.order_id LIKE ?
                OR COALESCE(at.raw_label, '') LIKE ?
              )
            ORDER BY COALESCE(at.txn_date, o.order_date, '0000-00-00') DESC, at.amazon_txn_id DESC
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


@app.get("/transactions/{amazon_txn_id}")
def get_transaction(amazon_txn_id: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        return _load_transaction_with_budget(conn, amazon_txn_id)
    finally:
        conn.close()


@app.get("/transactions/{amazon_txn_id}/items")
def transaction_items(amazon_txn_id: str):
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
            WHERE oit.amazon_txn_id = ?
            ORDER BY oi.item_id
            """,
            (amazon_txn_id,),
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
                o.order_date,
                o.order_url,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents,
                oi.item_tax_cents,
                oi.amazon_transaction_id
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
                o.order_date,
                o.order_url,
                o.order_total_cents,
                o.tax_cents,
                oi.title,
                oi.quantity,
                oi.item_subtotal_cents,
                oi.item_tax_cents,
                oi.amazon_transaction_id
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
                at.amazon_txn_id,
                at.order_id,
                at.txn_date,
                at.amount_cents,
                at.raw_label,
                at.budget_category_id,
                at.budget_subcategory_id,
                oit.allocated_amount_cents,
                oit.method
            FROM order_item_transactions oit
            JOIN amazon_transactions at ON at.amazon_txn_id = oit.amazon_txn_id
            WHERE oit.item_id = ?
            ORDER BY COALESCE(at.txn_date, '0000-00-00') DESC, at.amazon_txn_id
            """,
            (item_id,),
        ).fetchall()
        return {"rows": _rows_to_dict(rows)}
    finally:
        conn.close()
