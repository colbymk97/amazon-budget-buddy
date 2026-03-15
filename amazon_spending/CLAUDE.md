# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Python Backend

```bash
# Install (dev mode)
pip install -e ".[dev]"
playwright install chromium

# Run CLI
amazon-spending init-db
amazon-spending collect --retailer amazon
amazon-spending import-transactions --csv PATH
amazon-spending db-status

# API server
uvicorn amazon_spending.api:app --reload --host 127.0.0.1 --port 8000

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

This is a **local-first budget reconciliation tool** that scrapes retailer order history into SQLite and matches it against imported bank/card transactions. No cloud services required.

### Data flow

1. `collect` → Playwright scrapes retailer orders → stored in SQLite
2. `import-transactions` → CSV bank statements → stored in SQLite
3. `matcher.py` → matches bank transactions to orders/shipments by amount + date
4. `export` → CSV reconciliation reports; or browse via React UI + FastAPI

### Key modules

| Module | Responsibility |
|--------|---------------|
| `retailers/base.py` | `RetailerCollector` ABC — all scrapers implement this |
| `retailers/amazon.py` | Playwright-based Amazon order scraper (~61KB) |
| `retailers/__init__.py` | `REGISTRY` dict mapping retailer name → collector class |
| `db.py` | SQLite connection, schema migrations (`_migrate_to_multi_retailer`) |
| `sql/schema.sql` | Source of truth for table DDL |
| `matcher.py` | Amount+date matching; confidence scoring |
| `importers.py` | CSV transaction import with upsert logic |
| `api.py` | FastAPI server; CORS for React frontend; thread-safe sync jobs |
| `actual_sync.py` | Optional sync to Actual Budget (`pip install -e ".[actual]"`) |

### Database

SQLite at `data/amazon_spending.sqlite3` (configurable). Key tables: `orders`, `shipments`, `order_items`, `retailer_transactions`, `transactions` (imported bank data), `matches`, `budget_categories`, `budget_subcategories`, `actual_budget_config`, `import_runs`.

All tables with retailer-specific data have a `retailer` column (multi-retailer migration handles legacy Amazon-only databases).

### Adding a new retailer

1. Create `retailers/<name>.py` implementing `RetailerCollector` from `retailers/base.py`
2. Register it in `retailers/__init__.py` `REGISTRY`

### Frontend

React 18 + Vite + React Router + TanStack Table + Tailwind CSS. API calls go to `http://localhost:8000`. Pages map to: orders, items, transactions, reports, admin (sync control), and a baby-sitter spending tracker.

## Configuration

- Line length: 120 (ruff)
- Ruff rules: E, F (ignoring E501, E402, F401)
- Mypy target: Python 3.12
- Pytest testpaths: `tests/`
