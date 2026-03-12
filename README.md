# amazon-spending

Local-first tooling to collect and store retailer order history in SQLite and
reconcile it with bank/card transactions. Supports Amazon today, with a
pluggable adapter interface for adding new retailers (e.g. Target).
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
amazon-spending collect --retailer amazon --order-limit 100

# 3. Check the current DB state
amazon-spending db-status
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
without touching existing data. Also runs the multi-retailer migration
(renaming `amazon_transactions` → `retailer_transactions`, etc.) if needed.

**Examples**

```bash
amazon-spending init-db
amazon-spending --db ~/my-data.sqlite3 init-db
```

---

### `collect`

Scrape retailer order history into the local database.

```
amazon-spending collect --retailer <name> [options]
```

**Supported retailers:** `amazon`, `target` *(Target scraping is not yet implemented — see [Adding a New Retailer](#adding-a-new-retailer))*

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--retailer NAME` | *(required)* | Retailer to collect from |
| `--start-date YYYY-MM-DD` | auto | Earliest order date (inclusive) |
| `--end-date YYYY-MM-DD` | auto | Latest order date (inclusive) |
| `--order-limit N` | unlimited | Maximum orders to collect |
| `--max-pages N` | derived | Maximum listing pages to traverse |

**Browser options**

| Flag | Default | Description |
|------|---------|-------------|
| `--headed` | off | Force a visible browser window |
| `--user-data-dir PATH` | `data/raw/<retailer>/browser_profile` | Persistent profile for session cookies |

**Storage options**

| Flag | Default | Description |
|------|---------|-------------|
| `--outdir PATH` | `data/raw/<retailer>` | Directory for raw HTML snapshots |
| `--test-run` | off | Parse a saved snapshot without launching browser |
| `--saved-run-dir PATH` | latest | Specific snapshot dir to parse (implies `--test-run`) |

**Incremental sync options**

| Flag | Default | Description |
|------|---------|-------------|
| `--stop-on-known` | off | Stop when a previously imported order is encountered |

**Output options**

| Flag | Description |
|------|-------------|
| `--json` | Print results as JSON instead of plain text |

**Examples**

```bash
# Collect the most recent 50 Amazon orders
amazon-spending collect --retailer amazon --order-limit 50

# Collect a specific date range
amazon-spending collect --retailer amazon --start-date 2024-01-01 --end-date 2024-06-30

# First-time login / MFA — use a visible browser
amazon-spending collect --retailer amazon --headed --order-limit 20

# Fastest incremental sync
amazon-spending collect --retailer amazon --stop-on-known

# Re-parse saved HTML without launching a browser
amazon-spending collect --retailer amazon --test-run

# Machine-readable JSON output
amazon-spending collect --retailer amazon --order-limit 10 --json
```

**Deprecated alias:** `collect-amazon` behaves identically to `collect --retailer amazon`.

---

### `import-transactions`

Import bank or credit-card transactions from a CSV file.

```
amazon-spending import-transactions --csv PATH [--account-id ID] [--json]
```

#### Required CSV Columns

| Column | Description |
|--------|-------------|
| `transaction_id` | Unique identifier for the transaction |
| `posted_date` | ISO date posted (`YYYY-MM-DD`) |
| `amount` | Amount in dollars (e.g. `42.99`) |
| `merchant_raw` | Raw merchant name from the statement |

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--csv PATH` | *(required)* | Path to the CSV file |
| `--account-id ID` | none | Tag rows with an account label |
| `--json` | off | Print results as JSON |

**Examples**

```bash
amazon-spending import-transactions --csv data/transactions.csv
amazon-spending import-transactions --csv data/amex.csv --account-id amex-gold
```

---

### `export`

Export reconciliation reports to CSV files.

```
amazon-spending export [--outdir PATH] [--json]
```

| Output File | Description |
|------------|-------------|
| `report_transaction_itemized.csv` | Each transaction matched to its order items |
| `report_unmatched.csv` | Transactions with no order match |
| `report_monthly_summary.csv` | Monthly totals by essential flag |

**Examples**

```bash
amazon-spending export
amazon-spending export --outdir ~/reports/2024
```

---

## React UI + API Server

```bash
# Terminal 1 — API server
uvicorn amazon_spending.api:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — React frontend
cd frontend && npm install && npm run dev
```

| Service | URL |
|---------|-----|
| React frontend | `http://127.0.0.1:5173` |
| API server | `http://127.0.0.1:8000` |

---

## Adding a New Retailer

1. Create `amazon_spending/retailers/<name>.py` implementing `RetailerCollector`:

```python
from amazon_spending.retailers.base import CollectResult, RetailerCollector

class TargetCollector(RetailerCollector):
    RETAILER_ID = "target"

    def collect(self, conn, output_dir, **kwargs) -> CollectResult:
        # scrape Target order history and reconcile into the DB
        ...
```

2. Register it in `amazon_spending/retailers/__init__.py`:

```python
from .target import TargetCollector

REGISTRY = {
    "amazon": AmazonCollector(),
    "target": TargetCollector(),
}
```

That's it — the CLI, API, and DB schema all pick it up automatically.
Each retailer's orders get a `retailer` column in the `orders` and
`retailer_transactions` tables so data from all retailers coexists cleanly.

---

## Database Schema Notes

- All data is stored in `data/amazon_spending.sqlite3` by default.
- `orders.retailer` and `retailer_transactions.retailer` identify which retailer each row came from.
- Existing Amazon-only databases are migrated automatically on `init-db` or first run:
  `amazon_transactions` → `retailer_transactions`, `amazon_txn_id` → `retailer_txn_id`.
- Raw HTML snapshots are saved under `data/raw/<retailer>/<timestamp>/`.
