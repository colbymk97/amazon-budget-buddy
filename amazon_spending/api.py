from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .db import connect, db_status_payload, init_db
from .exporter import export_reports

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_DB_PATH = PROJECT_ROOT / "data/amazon_spending.sqlite3"

app = FastAPI(title="Budget Buddy API", version="0.3.0")
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


def _ensure_api_db_schema() -> None:
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        init_db(conn)
    finally:
        conn.close()


_ensure_api_db_schema()


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
# Budget categories (categorization is an analytical/UI feature)
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
# CSV export (download-only; generation is pure read)
# ---------------------------------------------------------------------------

@app.get("/export/csv")
def export_csv():
    conn = connect(DEFAULT_API_DB_PATH)
    try:
        outdir = PROJECT_ROOT / "data" / "exports"
        paths = export_reports(conn, outdir)
    finally:
        conn.close()

    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _name, path in paths.items():
            if path.exists():
                zf.write(path, path.name)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=budget_buddy_export.zip"},
    )
