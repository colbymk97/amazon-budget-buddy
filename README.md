# Budget Buddy

Local-first tooling to collect and store retailer order history in SQLite and
sync it to Actual Budget for reconciliation. Supports Amazon today, with a
pluggable adapter interface for adding new retailers.
All data stays on your machine — no cloud services required.

## Installation

### Install into a virtual environment (recommended)

This registers the `budget-buddy` command so you can run it from anywhere
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

The `budget-buddy` command is now available whenever the venv is active:

```bash
budget-buddy --version
budget-buddy init-db
```

To activate the venv in a new terminal session:

```bash
source .venv/bin/activate
```

### Run without installing (using the module directly)

You can also invoke the package directly as a Python module from the repo root
without registering the `budget-buddy` entry-point:

```bash
source .venv/bin/activate
python3 -m budget_buddy init-db
python3 -m budget_buddy collect --retailer amazon --order-limit 50
python3 -m budget_buddy db-status
```

All commands and flags are identical — `python3 -m budget_buddy` is a
drop-in equivalent to `budget-buddy`.

---

## Quick Start

```bash
# 1. Initialize the database
budget-buddy init-db

# 2. Collect your Amazon orders (headless browser, auto-auth fallback)
budget-buddy collect --retailer amazon --order-limit 100

# 3. Check the current DB state
budget-buddy db-status
```

---

## CLI Reference

```
budget-buddy [--db PATH] [--version] [-h] <command> [options]
```

### Global Options

| Flag | Default | Description |
|------|---------|-------------|
| `--db PATH` | `data/amazon_spending.sqlite3` | SQLite database file path |
| `--version` | — | Print version and exit |
| `-h, --help` | — | Show help message and exit |

Run `budget-buddy <command> --help` for detailed help on any command.

---

### `init-db`

Initialize or migrate the SQLite schema.

```
budget-buddy init-db
```

Safe to run on an existing database — missing tables and columns are added
without touching existing data. Also runs the multi-retailer migration
(renaming `amazon_transactions` → `retailer_transactions`, etc.) if needed.

**Examples**

```bash
budget-buddy init-db
budget-buddy --db ~/my-data.sqlite3 init-db
```

---

### `collect`

Scrape retailer order history into the local database.

```
budget-buddy collect --retailer <name> [options]
```

**Supported retailers:** `amazon`

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
| `--save-raw always\|on-error\|never` | `always` | Raw HTML snapshot policy |
| `--raw-retention-runs N` | unlimited | Keep only the latest N timestamped raw snapshot runs |

**Incremental sync options**

| Flag | Default | Description |
|------|---------|-------------|
| `--stop-on-known` | off | Stop when a previously imported order is encountered |
| `--overlap-match-threshold N` | `1` | Known order IDs to encounter before stopping with `--stop-on-known` |

**Output options**

| Flag | Description |
|------|-------------|
| `--json` | Print results as JSON instead of plain text |

**Examples**

```bash
# Collect the most recent 50 Amazon orders
budget-buddy collect --retailer amazon --order-limit 50

# Collect a specific date range
budget-buddy collect --retailer amazon --start-date 2024-01-01 --end-date 2024-06-30

# First-time login / MFA — use a visible browser
budget-buddy collect --retailer amazon --headed --order-limit 20

# Fastest incremental sync
budget-buddy collect --retailer amazon --stop-on-known

# Safer incremental sync with extra overlap
budget-buddy collect --retailer amazon --stop-on-known --overlap-match-threshold 2

# Reduce raw snapshot disk usage
budget-buddy collect --retailer amazon --save-raw on-error --raw-retention-runs 10

# Re-parse saved HTML without launching a browser
budget-buddy collect --retailer amazon --test-run

# Machine-readable JSON output
budget-buddy collect --retailer amazon --order-limit 10 --json
```

**Deprecated alias:** `collect-amazon` behaves identically to `collect --retailer amazon`.

---

### `actual-configure`

Store Actual Budget settings in the local SQLite database.

```
budget-buddy actual-configure [options]
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
budget-buddy actual-configure --base-url http://localhost:5006 --file "My Budget"
budget-buddy actual-configure --account-name "Chase Sapphire"
budget-buddy actual-configure --show
```

---

### `actual-sync`

Push unsynced retailer transactions to Actual Budget using the stored config.

```
budget-buddy actual-sync [--dry-run] [--json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Preview matches without writing to Actual or the local DB |
| `--json` | off | Print results as JSON |

**Examples**

```bash
budget-buddy actual-sync --dry-run
budget-buddy actual-sync
```

---

## React UI + API Server

```bash
# Terminal 1 — API server
uvicorn budget_buddy.api:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — React frontend
cd frontend && npm install && npm run dev
```

| Service | URL |
|---------|-----|
| React frontend | `http://127.0.0.1:5173` |
| API server | `http://127.0.0.1:8000` |

---

## Adding a New Retailer

1. Create `budget_buddy/retailers/<name>.py` implementing `RetailerCollector`:

```python
from budget_buddy.retailers.base import CollectResult, RetailerCollector

class TargetCollector(RetailerCollector):
    RETAILER_ID = "target"

    def collect(self, conn, output_dir, **kwargs) -> CollectResult:
        # scrape Target order history and reconcile into the DB
        ...
```

2. Register it in `budget_buddy/retailers/__init__.py`:

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
