from __future__ import annotations

import io
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .db import (
    connect,
    db_status_payload,
    delete_retailer_credentials,
    get_retailer_credentials,
    init_db,
    upsert_retailer_credentials,
)
from .exporter import export_reports
from .importers import import_transactions_csv
from .retailers import REGISTRY

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DB_PATH = PROJECT_ROOT / "data/amazon_spending.sqlite3"
DEFAULT_RAW_OUTDIR = PROJECT_ROOT / "data/raw/amazon"

app = FastAPI(title="Budget Buddy API", version="0.2.0")
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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

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


class CredentialsUpsert(BaseModel):
    email: str
    password: str
    otp_secret: Optional[str] = None
    cookie_jar_path: Optional[str] = None


class ActualConfigUpsert(BaseModel):
    base_url: str
    password: str
    file: str
    account_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _sync_completion_note(since_date: str | None, new_orders: int, new_txns: int) -> str:
    since_label = since_date or "the beginning"
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


# ---------------------------------------------------------------------------
# Sync job
# ---------------------------------------------------------------------------

def _try_actual_sync_after_import(new_txns: int) -> str:
    """If Actual Budget is configured, automatically sync pending transactions.

    Returns a short note string to append to the sync completion message,
    or empty string if Actual is not configured or nothing was synced.
    """
    if new_txns == 0:
        return ""
    try:
        from .actual_sync import load_config, sync_to_actual

        conn = connect(DEFAULT_API_DB_PATH)
        try:
            config = load_config(conn)
            if not config:
                return ""
            result = sync_to_actual(conn, config, dry_run=False)
            if result.synced > 0:
                return f"Synced {result.synced} transaction(s) to Actual Budget."
            return ""
        finally:
            conn.close()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Auto Actual sync failed: %s", exc)
        return ""


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

        sync_start_date = _incremental_start_date(before_order_date, overlap_days=2)

        _set_sync_state(
            progress=15,
            stage="collecting",
            last_order_date=before_order_date,
            last_transaction_date=before_txn_date,
            sync_since_date=before_order_date,
            notes=(
                f"Collecting latest orders and transactions "
                f"(since={before_order_date or 'full import'})..."
            ),
        )

        conn = connect(DEFAULT_API_DB_PATH)
        try:
            result = REGISTRY["amazon"].collect(
                conn=conn,
                output_dir=DEFAULT_RAW_OUTDIR,
                start_date=sync_start_date,
                should_abort=_cancel_requested,
                known_order_ids=recent_known_order_ids,
            )
        finally:
            conn.close()

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
                new_orders_added=0,
            )
            return

        if result.status in ("auth_required", "error"):
            _set_sync_state(
                running=False,
                cancel_requested=False,
                progress=100,
                stage="error",
                finished_at=_utcnow_iso(),
                status=result.status,
                notes=result.notes,
                error=result.notes,
                new_orders_added=0,
                new_transactions_added=0,
            )
            return

        _set_sync_state(progress=90, stage="finalizing", notes="Finalizing import...")
        conn_after = connect(DEFAULT_API_DB_PATH)
        try:
            after_order_date, after_txn_date = _latest_dates(conn_after)
        finally:
            conn_after.close()

        new_txns = result.amazon_txns_inserted
        new_orders = result.orders_inserted
        notes = _sync_completion_note(before_order_date, new_orders, new_txns)
        if result.notes:
            notes = f"{notes} {result.notes}".strip()

        # Auto-sync to Actual Budget if configured and there are new transactions.
        actual_note = _try_actual_sync_after_import(new_txns)
        if actual_note:
            notes = f"{notes} {actual_note}".strip()

        _set_sync_state(
            running=False,
            cancel_requested=False,
            progress=100,
            stage="complete",
            finished_at=_utcnow_iso(),
            status="ok",
            notes=notes,
            error=None,
            last_order_date=after_order_date,
            last_transaction_date=after_txn_date,
            new_transactions_added=new_txns,
            new_orders_added=new_orders,
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
            new_orders_added=0,
        )


def _ensure_api_db_schema() -> None:
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        init_db(conn)
    finally:
        conn.close()


_ensure_api_db_schema()


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Health / DB status
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/db/status")
def db_status_endpoint():
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        return db_status_payload(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

@app.get("/credentials/{retailer}")
def get_credentials(retailer: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        row = get_retailer_credentials(conn, retailer)
        if not row:
            return {"configured": False}
        return {
            "configured": True,
            "email": row["email"],
            "has_otp_secret": bool(row["otp_secret"]),
            "cookie_jar_path": row["cookie_jar_path"] or None,
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


@app.post("/credentials/{retailer}")
def save_credentials(retailer: str, payload: CredentialsUpsert):
    if not payload.email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="Password is required")
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        upsert_retailer_credentials(
            conn,
            retailer,
            payload.email.strip(),
            payload.password,
            payload.otp_secret or None,
            payload.cookie_jar_path.strip() or None if payload.cookie_jar_path else None,
        )
        return {"saved": True}
    finally:
        conn.close()


@app.delete("/credentials/{retailer}")
def remove_credentials(retailer: str):
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        deleted = delete_retailer_credentials(conn, retailer)
        return {"deleted": deleted}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Browser-based Amazon authentication
# ---------------------------------------------------------------------------

_AUTH_LOCK = threading.Lock()
_AUTH_STATE: dict[str, Any] = {
    "running": False,
    "status": "idle",  # idle | browser_open | authenticated | error | timeout | cancelled
    "message": "",
    "started_at": None,
    "finished_at": None,
}
_AUTH_CANCEL = threading.Event()

DEFAULT_COOKIE_JAR = PROJECT_ROOT / "data/cookies/amazon_cookies.json"
DEFAULT_BROWSER_PROFILE = PROJECT_ROOT / "data/browser_profiles/amazon"


def _set_auth_state(**kwargs: Any) -> None:
    with _AUTH_LOCK:
        _AUTH_STATE.update(kwargs)


def _auth_snapshot() -> dict[str, Any]:
    with _AUTH_LOCK:
        return dict(_AUTH_STATE)


def _run_browser_login() -> None:
    from .browser_auth import browser_login_amazon

    cookie_jar = str(DEFAULT_COOKIE_JAR)
    profile = str(DEFAULT_BROWSER_PROFILE)

    def on_status(msg: str) -> None:
        _set_auth_state(message=msg)

    _set_auth_state(
        running=True,
        status="browser_open",
        message="Browser window opened — please log in to Amazon.",
        started_at=_utcnow_iso(),
        finished_at=None,
    )

    result = browser_login_amazon(
        cookie_jar_path=cookie_jar,
        profile_dir=profile,
        timeout_seconds=300,
        on_status=on_status,
        cancel_event=_AUTH_CANCEL,
    )

    finished = _utcnow_iso()

    if result.status == "ok":
        # Persist the cookie jar path in retailer_credentials.
        conn = connect(DEFAULT_API_DB_PATH)
        try:
            conn.execute(
                "UPDATE retailer_credentials SET cookie_jar_path = ?, updated_at = datetime('now') WHERE retailer = ?",
                (cookie_jar, "amazon"),
            )
            conn.commit()
        finally:
            conn.close()

    _set_auth_state(
        running=False,
        status=result.status,
        message=result.message,
        finished_at=finished,
    )


@app.get("/auth/amazon/browser-login/status")
def browser_login_status():
    return _auth_snapshot()


@app.post("/auth/amazon/browser-login")
def start_browser_login():
    snap = _auth_snapshot()
    if snap.get("running"):
        raise HTTPException(status_code=409, detail="Browser login already running.")
    # Ensure credentials exist before launching browser.
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        row = get_retailer_credentials(conn, "amazon")
        if not row:
            raise HTTPException(
                status_code=400,
                detail="Save Amazon credentials first before using Browser Login.",
            )
    finally:
        conn.close()

    _AUTH_CANCEL.clear()
    t = threading.Thread(target=_run_browser_login, daemon=True)
    t.start()
    return {"started": True}


@app.post("/auth/amazon/browser-login/cancel")
def cancel_browser_login():
    _AUTH_CANCEL.set()
    _set_auth_state(message="Cancellation requested...")
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@app.post("/import/transactions")
async def import_transactions(
    file: UploadFile,
    account_id: Optional[str] = Query(default=None),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")

    content = await file.read()
    tmp_path = PROJECT_ROOT / "data" / f"_upload_{file.filename}"
    try:
        tmp_path.write_bytes(content)
        conn = connect(DEFAULT_API_DB_PATH)
        try:
            count = import_transactions_csv(conn, tmp_path, account_id=account_id or None)
        finally:
            conn.close()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"imported": count}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@app.get("/export/csv")
def export_csv():
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        outdir = PROJECT_ROOT / "data" / "exports"
        paths = export_reports(conn, outdir)
    finally:
        conn.close()

    # Return a zip of all report files
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in paths.items():
            if path.exists():
                zf.write(path, path.name)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=budget_buddy_export.zip"},
    )


# ---------------------------------------------------------------------------
# Budget categories
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

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
                COUNT(DISTINCT at.retailer_txn_id) AS txn_count
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            LEFT JOIN retailer_transactions at ON at.order_id = o.order_id
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
                retailer_txn_id,
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


# ---------------------------------------------------------------------------
# Retailer transactions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

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
# Actual Budget integration
# ---------------------------------------------------------------------------

@app.get("/actual/status")
def actual_status():
    from .actual_sync import load_config

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        cfg = load_config(conn)
        if not cfg:
            return {"configured": False, "pending": 0}
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM retailer_transactions
            WHERE actual_synced_at IS NULL
              AND txn_date IS NOT NULL
              AND amount_cents IS NOT NULL
            """
        ).fetchone()
        pending = row["n"] if row else 0
    finally:
        conn.close()
    return {
        "configured": True,
        "base_url": cfg.base_url,
        "file": cfg.file,
        "account_name": cfg.account_name,
        "pending": pending,
    }


@app.post("/actual/configure")
def actual_configure(payload: ActualConfigUpsert):
    if not payload.base_url.strip():
        raise HTTPException(status_code=400, detail="base_url is required")
    if not payload.file.strip():
        raise HTTPException(status_code=400, detail="file is required")
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="password is required")

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO actual_budget_config (singleton_id, base_url, password, file, account_name, updated_at)
            VALUES (1, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(singleton_id) DO UPDATE SET
                base_url = excluded.base_url,
                password = excluded.password,
                file = excluded.file,
                account_name = excluded.account_name,
                updated_at = datetime('now')
            """,
            (payload.base_url.strip(), payload.password, payload.file.strip(), payload.account_name),
        )
        conn.commit()
    finally:
        conn.close()
    return {"saved": True}


@app.delete("/actual/configure")
def actual_configure_delete():
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        conn.execute("DELETE FROM actual_budget_config WHERE singleton_id = 1")
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True}


@app.post("/actual/sync")
def actual_sync(dry_run: bool = Query(False)):
    from .actual_sync import load_config, sync_to_actual

    conn = connect(DEFAULT_API_DB_PATH)
    try:
        cfg = load_config(conn)
        if not cfg:
            raise HTTPException(
                status_code=400,
                detail="Actual Budget is not configured. Add it in Settings first.",
            )
        result = sync_to_actual(conn, cfg, dry_run=dry_run)
    finally:
        conn.close()
    return {"dry_run": dry_run, **result.to_dict()}
