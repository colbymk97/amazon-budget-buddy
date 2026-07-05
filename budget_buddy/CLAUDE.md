# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working conventions

This is a single-owner personal project with no external API consumers. When new work supersedes old code (old endpoints, old UI copy, old components, old DB columns/tables), **delete it outright** — don't keep it around for backwards compatibility, don't add deprecation shims, don't leave "legacy" code paths. There is no user base to protect. Still back up the real local SQLite DB before destructive schema changes.

## Commands

### Python Backend

```bash
# Install (dev mode)
pip install -e ".[dev]"
playwright install chromium

# Run CLI
budget-buddy init-db
budget-buddy collect --retailer amazon
budget-buddy db-status

# API server
uvicorn budget_buddy.api:app --reload --host 127.0.0.1 --port 8000

# Tests
pytest
pytest tests/test_amazon_collect_logic.py   # single test file

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
npm run lint
```

## Architecture

This is a **local-first budget reconciliation tool** that scrapes retailer order history into SQLite and syncs it to Actual Budget. No cloud services required.

### Data flow

1. `collect` → Playwright scrapes retailer orders and their per-charge transactions → stored in SQLite (`orders`, `retailer_transactions`)
2. `actual-sync` → matches `retailer_transactions` against Actual Budget's own transactions by amount + date, appends order/item notes; browse everything via React UI + FastAPI

### Key modules

| Module | Responsibility |
|--------|---------------|
| `retailers/base.py` | `RetailerCollector` ABC — all scrapers implement this |
| `retailers/amazon.py` | Playwright-based Amazon order scraper (~61KB) |
| `retailers/__init__.py` | `REGISTRY` dict mapping retailer name → collector class |
| `db.py` | SQLite connection, schema migrations (`_migrate_to_multi_retailer`) |
| `sql/schema.sql` | Source of truth for table DDL |
| `api.py` | FastAPI server; CORS for React frontend; thread-safe sync jobs |
| `actual_sync.py` | Optional sync to Actual Budget (`pip install -e ".[actual]"`) |

### Database

SQLite at `data/amazon_spending.sqlite3` (configurable). Key tables: `orders`, `shipments`, `order_items`, `retailer_transactions` (per-charge Amazon transaction data), `budget_categories`, `budget_subcategories`, `actual_budget_config`, `retailer_import_runs`.

All tables with retailer-specific data have a `retailer` column (multi-retailer migration handles legacy Amazon-only databases).

### Adding a new retailer

1. Create `retailers/<name>.py` implementing `RetailerCollector` from `retailers/base.py`
2. Register it in `retailers/__init__.py` `REGISTRY`

### Frontend

React 18 + Vite + React Router + TanStack Table + Recharts, hand-written CSS (no utility framework). API calls go to `http://localhost:8000`. Pages map to: dashboard (spend charts), status (sync control + Actual reconciliation), orders, items, transactions, reports, and budget categories (read-only mirror of Actual's categories).

## Configuration

- Line length: 120 (ruff)
- Ruff rules: E, F (ignoring E501, E402, F401)
- Mypy target: Python 3.12
- Pytest testpaths: `tests/`
