PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    retailer TEXT NOT NULL DEFAULT 'amazon',
    order_date TEXT NOT NULL,
    order_url TEXT,
    order_total_cents INTEGER NOT NULL,
    tax_cents INTEGER,
    shipping_cents INTEGER,
    payment_last4 TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    ship_date TEXT,
    shipment_total_cents INTEGER NOT NULL,
    status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS retailer_transactions (
    retailer_txn_id TEXT PRIMARY KEY,
    retailer TEXT NOT NULL DEFAULT 'amazon',
    order_id TEXT NOT NULL,
    transaction_tag TEXT,
    txn_date TEXT,
    amount_cents INTEGER,
    payment_last4 TEXT,
    raw_label TEXT,
    source_url TEXT,
    budget_category_id INTEGER,
    budget_subcategory_id INTEGER,
    actual_synced_at TEXT,
    actual_category_id TEXT,
    actual_category_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(order_id) REFERENCES orders(order_id),
    FOREIGN KEY(budget_category_id) REFERENCES budget_categories(category_id),
    FOREIGN KEY(budget_subcategory_id) REFERENCES budget_subcategories(subcategory_id)
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

CREATE TABLE IF NOT EXISTS order_items (
    item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    shipment_id TEXT,
    retailer_transaction_id TEXT,
    title TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    item_subtotal_cents INTEGER NOT NULL,
    item_tax_cents INTEGER,
    essential_flag INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(order_id) REFERENCES orders(order_id),
    FOREIGN KEY(shipment_id) REFERENCES shipments(shipment_id),
    FOREIGN KEY(retailer_transaction_id) REFERENCES retailer_transactions(retailer_txn_id)
);

CREATE TABLE IF NOT EXISTS order_item_transactions (
    item_id TEXT NOT NULL,
    retailer_txn_id TEXT NOT NULL,
    allocated_amount_cents INTEGER,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (item_id, retailer_txn_id),
    FOREIGN KEY(item_id) REFERENCES order_items(item_id),
    FOREIGN KEY(retailer_txn_id) REFERENCES retailer_transactions(retailer_txn_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY,
    posted_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    merchant_raw TEXT NOT NULL,
    description TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    account_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT NOT NULL,
    order_id TEXT,
    shipment_id TEXT,
    item_id TEXT,
    allocated_amount_cents INTEGER NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(txn_id) REFERENCES transactions(txn_id),
    FOREIGN KEY(order_id) REFERENCES orders(order_id),
    FOREIGN KEY(shipment_id) REFERENCES shipments(shipment_id),
    FOREIGN KEY(item_id) REFERENCES order_items(item_id)
);

CREATE TABLE IF NOT EXISTS manual_overrides (
    override_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_txn_id TEXT NOT NULL,
    selected_order_id TEXT,
    selected_item_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(target_txn_id) REFERENCES transactions(txn_id),
    FOREIGN KEY(selected_order_id) REFERENCES orders(order_id),
    FOREIGN KEY(selected_item_id) REFERENCES order_items(item_id)
);

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

CREATE TABLE IF NOT EXISTS actual_budget_config (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    base_url TEXT NOT NULL,
    password TEXT NOT NULL,
    file TEXT NOT NULL,
    account_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_retailer ON orders(retailer);
CREATE INDEX IF NOT EXISTS idx_shipments_order_id ON shipments(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_shipment_id ON order_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_order_items_retailer_txn_id ON order_items(retailer_transaction_id);
CREATE INDEX IF NOT EXISTS idx_retailer_transactions_order_id ON retailer_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_retailer_transactions_retailer ON retailer_transactions(retailer);
CREATE INDEX IF NOT EXISTS idx_retailer_transactions_budget_category_id ON retailer_transactions(budget_category_id);
CREATE INDEX IF NOT EXISTS idx_retailer_transactions_budget_subcategory_id ON retailer_transactions(budget_subcategory_id);
CREATE INDEX IF NOT EXISTS idx_order_item_transactions_item ON order_item_transactions(item_id);
CREATE INDEX IF NOT EXISTS idx_order_item_transactions_txn ON order_item_transactions(retailer_txn_id);
CREATE INDEX IF NOT EXISTS idx_transactions_posted_date ON transactions(posted_date);
CREATE INDEX IF NOT EXISTS idx_matches_txn_id ON matches(txn_id);
CREATE INDEX IF NOT EXISTS idx_budget_subcategories_category_id ON budget_subcategories(category_id);
CREATE INDEX IF NOT EXISTS idx_retailer_import_runs_retailer_finished ON retailer_import_runs(retailer, finished_at DESC);
