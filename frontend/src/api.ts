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

export function getHealth() {
  return getJson<{ status: string }>(`/health`);
}

export type SyncStatus = {
  running: boolean;
  cancel_requested?: boolean;
  progress: number;
  stage: string;
  started_at?: string | null;
  finished_at?: string | null;
  last_order_date?: string | null;
  last_transaction_date?: string | null;
  new_transactions_added?: number;
  new_orders_added?: number;
  sync_since_date?: string | null;
  status?: string;
  notes?: string;
  error?: string | null;
};

export function getSyncStatus() {
  return getJson<SyncStatus>(`/sync/status`);
}

export async function startSync() {
  const res = await fetch(`${API_BASE}/sync/start`, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<{ started: boolean; message: string }>;
}

export async function cancelSync() {
  const res = await fetch(`${API_BASE}/sync/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<{ cancelled: boolean; message: string }>;
}

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

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

export type CredentialsStatus = {
  configured: boolean;
  email?: string;
  has_otp_secret?: boolean;
  cookie_jar_path?: string | null;
  updated_at?: string;
};

export function getCredentials(retailer: string) {
  return getJson<CredentialsStatus>(`/credentials/${retailer}`);
}

export async function saveCredentials(
  retailer: string,
  payload: { email: string; password: string; otp_secret?: string; cookie_jar_path?: string }
) {
  const res = await fetch(`${API_BASE}/credentials/${retailer}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `API ${res.status}`);
  }
  return res.json() as Promise<{ saved: boolean }>;
}

export async function deleteCredentials(retailer: string) {
  const res = await fetch(`${API_BASE}/credentials/${retailer}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<{ deleted: boolean }>;
}

// ---------------------------------------------------------------------------
// Browser-based Amazon authentication
// ---------------------------------------------------------------------------

export type BrowserLoginStatus = {
  running: boolean;
  status: string;
  message: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export function getBrowserLoginStatus() {
  return getJson<BrowserLoginStatus>("/auth/amazon/browser-login/status");
}

export async function startBrowserLogin() {
  const res = await fetch(`${API_BASE}/auth/amazon/browser-login`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `API ${res.status}`);
  }
  return res.json() as Promise<{ started: boolean }>;
}

export async function cancelBrowserLogin() {
  const res = await fetch(`${API_BASE}/auth/amazon/browser-login/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<{ cancelled: boolean }>;
}

// ---------------------------------------------------------------------------
// Actual Budget config
// ---------------------------------------------------------------------------

export type ActualStatus = {
  configured: boolean;
  base_url?: string;
  file?: string;
  account_name?: string;
  pending?: number;
};

export function getActualStatus() {
  return getJson<ActualStatus>(`/actual/status`);
}

export async function saveActualConfig(payload: {
  base_url: string;
  password: string;
  file: string;
  account_name?: string;
}) {
  const res = await fetch(`${API_BASE}/actual/configure`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `API ${res.status}`);
  }
  return res.json() as Promise<{ saved: boolean }>;
}

export async function deleteActualConfig() {
  const res = await fetch(`${API_BASE}/actual/configure`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<{ deleted: boolean }>;
}

export async function runActualSync(dry_run = false) {
  const res = await fetch(`${API_BASE}/actual/sync?dry_run=${dry_run}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `API ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// CSV import / export
// ---------------------------------------------------------------------------

export async function importTransactionsCsv(file: File, account_id?: string) {
  const form = new FormData();
  form.append("file", file);
  const url = `${API_BASE}/import/transactions${account_id ? `?account_id=${encodeURIComponent(account_id)}` : ""}`;
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `API ${res.status}`);
  }
  return res.json() as Promise<{ imported: number }>;
}

export function getExportUrl() {
  return `${API_BASE}/export/csv`;
}

// ---------------------------------------------------------------------------
// DB status
// ---------------------------------------------------------------------------

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
