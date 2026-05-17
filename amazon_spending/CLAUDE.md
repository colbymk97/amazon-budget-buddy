# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Python Backend

```bash
# Install (dev mode)
pip install -e ".[dev,actual]"
playwright install chromium

# CLI — primary operational interface
amazon-spending --help
amazon-spending init-db
amazon-spending login --retailer amazon
amazon-spending collect --retailer amazon --order-limit 50
amazon-spending actual-sync

# API server (read-only viewer; CLI handles all writes)
uvicorn amazon_spending.api:app --reload --host 127.0.0.1 --port 8000

# Tests
pytest
pytest tests/test_amazon_collect_logic.py

# Lint / type check
ruff check .
mypy .
```

### React Frontend

```bash
cd frontend
npm install
npm run dev      # dev server on port 5173
npm run build
```

## Architecture

Local-first budget reconciliation tool. Two components, sharp boundary:

- **CLI** (`amazon_spending.cli`) owns all writes. Scrapes Amazon via Playwright into the SQLite database, imports bank/card CSVs, runs Actual Budget syncs, exports reports. Authenticates via a persistent Chromium profile at `data/raw/amazon/browser_profile` — first run opens a headed browser for one-time login, subsequent runs reuse the profile silently.
- **Web app** (FastAPI + React) is a **strict read-only viewer** over the same SQLite file. No sync buttons. No auth flows. The one exception: budget categorization (assigning categories to transactions) is a UI-driven analytical feature and remains as a mutation endpoint set.

### Data flow

1. `amazon-spending login --retailer amazon` — opens headed browser; user logs in; cookies persisted to the Chromium profile.
2. `amazon-spending collect --retailer amazon [--start-date ...]` — Playwright scrapes order history pages and per-order detail / related-transactions pages, parses the HTML with regex extractors in `retailers/amazon.py`, reconciles into `orders`, `order_items`, `retailer_transactions`, `shipments`, `order_item_transactions`.
3. `amazon-spending import-transactions --csv ...` — imports bank/card CSVs into `transactions`.
4. `matcher.py` — matches bank transactions to retailer orders by amount + date.
5. `amazon-spending actual-sync` — pushes unsynced retailer transactions to Actual Budget.
6. Web app renders whatever is in the DB — no triggering, no writing (except budget categorization).

### Key modules

| Module | Responsibility |
|--------|---------------|
| `cli.py` | argparse-based CLI; primary operational interface |
| `retailers/base.py` | `RetailerCollector` ABC, `CollectResult` / `ParsedOrder` / `ParsedItem` / `ParsedRetailerTransaction` dataclasses |
| `retailers/amazon.py` | Playwright + regex Amazon scraper (`AmazonCollector`, `collect_amazon`) |
| `retailers/__init__.py` | `REGISTRY` dict mapping retailer name → collector instance |
| `db.py` | SQLite connection, schema migrations, retailer-account helpers |
| `sql/schema.sql` | Source of truth for table DDL |
| `matcher.py` | Amount+date matching; confidence scoring |
| `importers.py` | CSV transaction import with upsert logic |
| `exporter.py` | CSV report generation |
| `audit.py` | Compare Amazon listing pages against the local DB without mutating |
| `api.py` | FastAPI server; **read-only** endpoints plus budget categorization mutations |
| `actual_sync.py` | Optional sync to Actual Budget (`pip install -e ".[actual]"`) |

### Database

SQLite at `data/amazon_spending.sqlite3`. Key tables: `orders`, `shipments`, `order_items`, `retailer_transactions`, `order_item_transactions`, `transactions` (imported bank data), `matches`, `budget_categories`, `budget_subcategories`, `actual_budget_config`, `retailer_accounts`, `retailer_import_runs`.

All retailer-specific tables have a `retailer` column (multi-retailer ready).

### Amazon auth

Playwright with a persistent Chromium profile at `data/raw/amazon/browser_profile`. First `collect` or `login` opens a headed browser for the user to sign in (CAPTCHA / 2FA handled manually). Profile cookies persist, so subsequent runs go fully headless. No credentials are stored in the database.

### Adding a new retailer

1. Create `retailers/<name>.py` implementing `RetailerCollector` from `retailers/base.py`.
2. Register it in `retailers/__init__.py` `REGISTRY`.
3. The `collect()` method signature: `conn, output_dir, *, start_date, end_date, order_limit, should_abort, known_order_ids` (concrete collectors may accept additional kwargs).

### Frontend pages

React 18 + Vite + React Router + TanStack Table. API at `http://localhost:8000`.

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — DB overview, retailer status, totals |
| `/orders` | Order history |
| `/transactions` | Retailer payment transactions (with budget categorization) |
| `/items` | Line items |
| `/reports` | Monthly analytics |
| `/admin` | Budget categories |
| `/baby-sister` | Bonus screen |

Sync/auth/credentials UI was removed — those operations live in the CLI now.

## Configuration

- Line length: 120 (ruff)
- Ruff rules: E, F (ignoring E501, E402, F401)
- Mypy target: Python 3.12
- Pytest testpaths: `tests/`
