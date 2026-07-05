export type Order = {
  order_id: string;
  retailer?: string;
  order_date: string;
  order_url?: string | null;
  order_total_cents: number;
  tax_cents?: number | null;
  shipping_cents?: number | null;
  payment_last4?: string | null;
  item_count?: number;
  txn_count?: number;
};

export type RetailerTransaction = {
  retailer_txn_id: string;
  retailer?: string;
  order_id: string;
  order_date?: string | null;
  order_url?: string | null;
  txn_date?: string | null;
  amount_cents?: number | null;
  payment_last4?: string | null;
  raw_label?: string | null;
  source_url?: string | null;
  order_total_cents?: number | null;
  tax_cents?: number | null;
  allocated_amount_cents?: number | null;
  method?: string | null;
  budget_category_id?: number | null;
  budget_subcategory_id?: number | null;
  budget_category_name?: string | null;
  budget_subcategory_name?: string | null;
};


export type OrderItem = {
  item_id: string;
  order_id: string;
  retailer?: string | null;
  order_date?: string | null;
  order_url?: string | null;
  title: string;
  quantity: number;
  item_subtotal_cents: number;
  item_tax_cents?: number | null;
  retailer_transaction_id?: string | null;
  order_total_cents?: number | null;
  tax_cents?: number | null;
  allocated_amount_cents?: number | null;
  method?: string | null;
};

// budget_categories/budget_subcategories are a read-only mirror of Actual
// Budget's own category groups/categories — never created by hand here.
export type BudgetCategory = {
  category_id: number;
  actual_group_id?: string | null;
  name: string;
  description?: string | null;
  subcategory_count?: number;
};

export type BudgetSubcategory = {
  subcategory_id: number;
  category_id: number;
  actual_category_id?: string | null;
  category_name?: string;
  name: string;
  description?: string | null;
};

export type RetailerStatus = {
  retailer: string;
  orders: number;
  transactions: number;
  first_order_date?: string | null;
  latest_order_date?: string | null;
  last_import_finished_at?: string | null;
  last_import_status?: string | null;
  bound_account?: string | null;
};

export type ActualStatus = {
  configured: boolean;
  base_url?: string | null;
  file?: string | null;
  account_name?: string | null;
  pending: number;
  total_transactions: number;
  synced: number;
  skipped: number;
  incomplete: number;
  last_synced_at?: string | null;
  skip_reasons: { reason: string | null; count: number }[];
};

export type MonthlyRetailerBreakdown = {
  order_count: number;
  gross_order_cents: number;
  txn_count: number;
  net_amount_cents: number;
};

export type MonthlySpend = {
  month: string;
  order_count: number;
  gross_order_cents: number;
  txn_count: number;
  net_amount_cents: number;
  by_retailer: Record<string, MonthlyRetailerBreakdown>;
};

export type SpendByMonthReport = {
  start_date: string;
  end_date: string;
  retailers: string[];
  months: MonthlySpend[];
};

export type RetailerSpend = {
  retailer: string;
  order_count: number;
  gross_order_cents: number;
  first_order_date?: string | null;
  latest_order_date?: string | null;
  txn_count: number;
  net_amount_cents: number;
};

export type SpendByRetailerReport = {
  start_date: string;
  end_date: string;
  retailers: RetailerSpend[];
};

export type CategorySpend = {
  id: number | null;
  name: string;
  txn_count: number;
  net_amount_cents: number;
};

export type SpendByCategoryReport = {
  start_date: string;
  end_date: string;
  category_id: number | null;
  rows: CategorySpend[];
};
