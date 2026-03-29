# amazon-spending

Local-first tooling to collect and store retailer order history in SQLite and
reconcile it with bank/card transactions. Supports Amazon today, with a
pluggable adapter interface for adding new retailers (e.g. Target).
All data stays on your machine — no cloud services required.

## Installation

### Install into a virtual environment (recommended)

This registers the `amazon-spending` command so you can run it from anywhere
while the venv is active. Run these from the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m ensurepip --upgrade     # bootstrap pip as a module
pip install --upgrade pip          # upgrade pip to support pyproject.toml installs
pip install -e .
playwright install chromium
```

> **Note:** The `ensurepip` and `pip upgrade` steps are required on macOS with
> the python.org Python 3.9 installer. Skipping them causes a
> `No module named pip` error during install.

The `amazon-spending` command is now available whenever the venv is active:

```bash
amazon-spending --version
amazon-spending init-db
```

To activate the venv in a new terminal session:

```bash
source .venv/bin/activate
```

### Run without installing (using the module directly)

You can also invoke the package directly as a Python module from the repo root
without registering the `amazon-spending` entry-point:

```bash
source .venv/bin/activate
python3 -m amazon_spending init-db
python3 -m amazon_spending collect --retailer amazon --order-limit 50
python3 -m amazon_spending db-status
```

All commands and flags are identical — `python3 -m amazon_spending` is a
drop-in equivalent to `amazon-spending`.

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

### `actual-configure`

Store Actual Budget settings in the local SQLite database.

```
amazon-spending actual-configure [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url URL` | existing | Actual server base URL |
| `--password TEXT` | prompt/existing | Actual password |
| `--file NAME` | existing | Actual budget file name |
| `--account-name NAME` | existing | Optional Actual account filter |
| `--clear-account-name` | off | Remove the stored account filter |
| `--show` | off | Show stored config without revealing the password |
| `--json` | off | Print results as JSON |

**Examples**

```bash
amazon-spending actual-configure --base-url http://localhost:5006 --file "My Budget"
amazon-spending actual-configure --account-name "Chase Sapphire"
amazon-spending actual-configure --show
```

---

### `actual-sync`

Push unsynced retailer transactions to Actual Budget using the stored config.

```
amazon-spending actual-sync [--dry-run] [--json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Preview matches without writing to Actual or the local DB |
| `--json` | off | Print results as JSON |

**Examples**

```bash
amazon-spending actual-sync --dry-run
amazon-spending actual-sync
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
