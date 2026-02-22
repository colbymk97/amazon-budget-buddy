export type Order = {
  order_id: string;
  order_date: string;
  order_url?: string | null;
  order_total_cents: number;
  tax_cents?: number | null;
  shipping_cents?: number | null;
  payment_last4?: string | null;
  item_count?: number;
  txn_count?: number;
};

export type AmazonTransaction = {
  amazon_txn_id: string;
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
  order_date?: string | null;
  order_url?: string | null;
  title: string;
  quantity: number;
  item_subtotal_cents: number;
  item_tax_cents?: number | null;
  amazon_transaction_id?: string | null;
  order_total_cents?: number | null;
  tax_cents?: number | null;
  allocated_amount_cents?: number | null;
  method?: string | null;
};

export type BudgetCategory = {
  category_id: number;
  name: string;
  description?: string | null;
  subcategory_count?: number;
};

export type BudgetSubcategory = {
  subcategory_id: number;
  category_id: number;
  category_name?: string;
  name: string;
  description?: string | null;
};
