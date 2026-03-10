# amazon-spending

Local-first tooling to collect and store personal Amazon order history in SQLite.
All data stays on your machine — no cloud services required.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

---

## Quick Start

```bash
# 1. Initialize the database
amazon-spending init-db

# 2. Collect your Amazon orders (headless browser, auto-auth fallback)
amazon-spending collect-amazon --order-limit 100

# 3. Browse orders in the local viewer
amazon-spending view
```

---

## CLI Reference

```
amazon-spending [--db PATH] [--version] [-h] <command> [options]
```

### Global Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `data/amazon_spending.sqlite3` | SQLite database file path |
| `--version` | — | Print version and exit |
| `-h, --help` | — | Show help message and exit |

Run `amazon-spending <command> --help` for detailed help on any command.

---

### `init-db`

Initialize or migrate the SQLite schema.

```
amazon-spending init-db
```

Safe to run on an existing database — missing tables and columns are added
without touching existing data.

**Examples**

```bash
# Initialize with the default database path
amazon-spending init-db

# Use a custom database file
amazon-spending --db ~/my-data.sqlite3 init-db
```

---

### `collect-amazon`

Scrape Amazon order history into the local database.

```
amazon-spending collect-amazon [options]
```

Launches a Playwright browser to collect orders, shipments, line items, and
payment transactions, then reconciles them into SQLite. The collector runs
headless by default and falls back to a visible browser window automatically
when Amazon requires interactive login or MFA.

#### Date / Scope Options

| Flag | Default | Description |
|------|---------|-------------|
| `--start-date YYYY-MM-DD` | auto | Earliest order date to collect (inclusive) |
| `--end-date YYYY-MM-DD` | auto | Latest order date to collect (inclusive) |
| `--order-limit N` | unlimited | Maximum number of orders to collect per run |
| `--max-pages N` | derived | Maximum listing pages to traverse |

#### Browser Options

| Flag | Default | Description |
|------|---------|-------------|
| `--headed` | off | Force a visible browser window |
| `--user-data-dir PATH` | `data/raw/amazon/browser_profile` | Persistent profile directory for session cookies |

#### Storage Options

| Flag | Default | Description |
|------|---------|-------------|
| `--outdir PATH` | `data/raw/amazon` | Directory for raw HTML snapshots |
| `--test-run` | off | Parse a saved snapshot without launching the browser |
| `--saved-run-dir PATH` | latest | Specific snapshot directory to parse (implies `--test-run`) |

#### Incremental Sync Options

| Flag | Default | Description |
|------|---------|-------------|
| `--stop-on-known` | off | Stop scanning when a previously imported order is encountered |

#### Output Options

| Flag | Description |
|------|-------------|
| `--json` | Print results as a JSON object instead of plain text |

**Examples**

```bash
# Collect the most recent 50 orders
amazon-spending collect-amazon --order-limit 50

# Collect a specific date range
amazon-spending collect-amazon --start-date 2024-01-01 --end-date 2024-06-30

# Force a visible browser window (useful for first-time login / MFA)
amazon-spending collect-amazon --headed --order-limit 20

# Re-parse previously saved HTML without launching a browser
amazon-spending collect-amazon --test-run

# Re-parse a specific saved snapshot directory
amazon-spending collect-amazon --saved-run-dir data/raw/amazon/20260216_081306

# Fastest incremental sync — stop as soon as known orders are reached
amazon-spending collect-amazon --stop-on-known

# Machine-readable JSON output
amazon-spending collect-amazon --order-limit 10 --json
```

**JSON output shape**

```json
{
  "status": "ok",
  "notes": "...",
  "orders_collected": 12,
  "items_collected": 34,
  "listing_pages_scanned": 2,
  "discovered_orders": 12,
  "known_orders_matched": 3,
  "reconciliation": {
    "orders":    { "inserted": 10, "updated": 2, "unchanged": 0 },
    "shipments": { "inserted": 11, "updated": 1, "unchanged": 0 },
    "items":     { "inserted": 30, "updated": 4, "unchanged": 0, "deleted": 0 },
    "amazon_transactions": { "inserted": 12, "updated": 0, "unchanged": 0, "deleted": 0 },
    "item_transaction_links_written": 34
  }
}
```

**How Incremental Import Decides How Far to Scan**

- Looks up the most recent imported order date in SQLite.
- Also loads the latest 30 known order IDs.
- Starts near the top of Amazon's order history and scans listing pages until
  a known order ID is encountered (`--stop-on-known`) or the page cap is reached.
- A 2-day date overlap is applied so borderline orders can be safely re-read and reconciled.
- If headless mode loads the page shell but surfaces no usable order data, the collector
  retries once in a visible browser window using the same persistent profile.

---

### `import-transactions`

Import bank or credit-card transactions from a CSV file.

```
amazon-spending import-transactions --csv PATH [--account-id ID] [--json]
```

Upserts rows into the local database for future reconciliation with Amazon orders.
Existing rows are updated on conflict — no duplicates are created for the same
`transaction_id`.

#### Required CSV Columns

| Column | Description |
|--------|-------------|
| `transaction_id` | Unique identifier for the bank/card transaction |
| `posted_date` | ISO date the transaction posted (`YYYY-MM-DD`) |
| `amount` | Transaction amount in dollars (e.g. `42.99` or `-12.50`) |
| `merchant_raw` | Raw merchant name as it appears on the statement |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--csv PATH` | *(required)* | Path to the transactions CSV file |
| `--account-id ID` | none | Label to tag rows with (e.g. `chase-freedom`) |
| `--json` | off | Print results as a JSON object instead of plain text |

**Examples**

```bash
# Import from a Copilot / Chase CSV export
amazon-spending import-transactions --csv data/transactions.csv

# Tag rows with an account label for multi-card households
amazon-spending import-transactions --csv data/amex.csv --account-id amex-gold

# Machine-readable JSON output
amazon-spending import-transactions --csv data/transactions.csv --json
```

---

### `export`

Export reconciliation reports to CSV files.

```
amazon-spending export [--outdir PATH] [--json]
```

Generates three CSV reports from the local database:

| File | Description |
|------|-------------|
| `report_transaction_itemized.csv` | Each transaction mapped to its matched Amazon order items |
| `report_unmatched.csv` | Transactions with no order match |
| `report_monthly_summary.csv` | Monthly spending totals grouped by essential flag |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--outdir PATH` | `data/exports` | Directory to write report files into |
| `--json` | off | Print a JSON summary of output file paths |

**Examples**

```bash
# Export to the default directory
amazon-spending export

# Export to a custom directory
amazon-spending export --outdir ~/reports/2024

# Machine-readable JSON output with file paths
amazon-spending export --json
```

---

### `view`

Open the local Streamlit web viewer.

```
amazon-spending view [--host HOST] [--port PORT]
```

Launches a Streamlit app for browsing orders, items, and transactions stored in
the local database.

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | `127.0.0.1` | Host address for the viewer server |
| `--port PORT` | `8501` | Port for the viewer server |

**Examples**

```bash
# Open the viewer on the default address
amazon-spending view

# Expose the viewer on all interfaces
amazon-spending view --host 0.0.0.0 --port 8888
```

> Requires Streamlit: `pip install streamlit`

---

## React UI + API Server

The newer React frontend requires two processes running in parallel:

```bash
# Terminal 1 — API server
uvicorn amazon_spending.api:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — React frontend
cd frontend
npm install
npm run dev
```

| Service | URL |
|---------|-----|
| React frontend | `http://127.0.0.1:5173` |
| API server | `http://127.0.0.1:8000` |

Set a custom API base URL if needed:

```bash
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

---

## Notes

- **Database** defaults to `./data/amazon_spending.sqlite3`.
- **Raw HTML snapshots** are saved under `data/raw/amazon/<timestamp>/` every collect run.
- **Reconciliation counts** (inserted / updated / unchanged) are printed at the end of every collect run.
- **Collector** also pulls related Amazon payment transactions and stores:
  - `amazon_transactions` (per-order Amazon transaction records)
  - `order_item_transactions` (item-to-transaction allocation links)
