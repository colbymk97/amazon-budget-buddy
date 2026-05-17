import type { RetailerTransaction, BudgetCategory, BudgetSubcategory, Order, OrderItem } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

type RowsResponse<T> = { rows: T[] };

function toQuery(params: Record<string, string | number | undefined>) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  });
  return sp.toString();
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<T>;
}

export function formatMoney(cents: number | null | undefined): string {
  const value = (cents ?? 0) / 100;
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

// ---------------------------------------------------------------------------
// Orders / Transactions / Items (read-only)
// ---------------------------------------------------------------------------

export function listOrders(params: {
  search?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}) {
  const q = toQuery(params);
  return getJson<RowsResponse<Order>>(`/orders?${q}`);
}

export function getOrder(orderId: string) {
  return getJson<Order>(`/orders/${orderId}`);
}

export function getOrderTransactions(orderId: string) {
  return getJson<RowsResponse<RetailerTransaction>>(`/orders/${orderId}/transactions`);
}

export function getOrderItems(orderId: string) {
  return getJson<RowsResponse<OrderItem>>(`/orders/${orderId}/items`);
}

export function listTransactions(params: {
  search?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}) {
  const q = toQuery(params);
  return getJson<RowsResponse<RetailerTransaction>>(`/transactions?${q}`);
}

export function getTransaction(txnId: string) {
  return getJson<RetailerTransaction>(`/transactions/${txnId}`);
}

export function getTransactionItems(txnId: string) {
  return getJson<RowsResponse<OrderItem>>(`/transactions/${txnId}/items`);
}

export function listItems(params: {
  search?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}) {
  const q = toQuery(params);
  return getJson<RowsResponse<OrderItem>>(`/items?${q}`);
}

export function getItem(itemId: string) {
  return getJson<OrderItem>(`/items/${itemId}`);
}

export function getItemTransactions(itemId: string) {
  return getJson<RowsResponse<RetailerTransaction>>(`/items/${itemId}/transactions`);
}

// ---------------------------------------------------------------------------
// Health / DB status
// ---------------------------------------------------------------------------

export function getHealth() {
  return getJson<{ status: string }>(`/health`);
}

export type DbRetailerStatus = {
  retailer: string;
  orders: number;
  transactions: number;
  first_order_date: string | null;
  latest_order_date: string | null;
  last_import_finished_at: string | null;
  last_import_status: string | null;
  bound_account: string | null;
};

export function getDbStatus() {
  return getJson<{ retailers: DbRetailerStatus[] }>(`/db/status`);
}

// ---------------------------------------------------------------------------
// Budget categorization (analytical UI feature — kept on the web)
// ---------------------------------------------------------------------------

export async function assignTransactionBudget(
  txnId: string,
  payload: { budget_category_id: number | null; budget_subcategory_id: number | null }
) {
  const res = await fetch(`${API_BASE}/transactions/${txnId}/budget`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<RetailerTransaction>;
}

export function listBudgetCategories() {
  return getJson<RowsResponse<BudgetCategory>>(`/budget/categories`);
}

export async function createBudgetCategory(payload: { name: string; description?: string }) {
  const res = await fetch(`${API_BASE}/budget/categories`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<BudgetCategory>;
}

export function listBudgetSubcategories(category_id?: number) {
  const q = toQuery({ category_id });
  return getJson<RowsResponse<BudgetSubcategory>>(`/budget/subcategories${q ? `?${q}` : ""}`);
}

export async function createBudgetSubcategory(payload: {
  category_id: number;
  name: string;
  description?: string;
}) {
  const res = await fetch(`${API_BASE}/budget/subcategories`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<BudgetSubcategory>;
}

// ---------------------------------------------------------------------------
// CSV export (download)
// ---------------------------------------------------------------------------

export function getExportUrl() {
  return `${API_BASE}/export/csv`;
}
