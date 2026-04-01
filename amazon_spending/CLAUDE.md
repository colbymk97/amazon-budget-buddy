# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Python Backend

```bash
# Install (dev mode)
pip install -e ".[dev]"

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

This is a **local-first budget reconciliation tool** that fetches retailer order history into SQLite and matches it against imported bank/card transactions. No cloud services required. Everything is managed through the web app — there is no CLI.

### Data flow

1. User enters Amazon credentials in Settings → stored in `retailer_credentials` table
2. Sync triggered via dashboard → `amazon-orders` library fetches orders + transactions → stored in SQLite
3. CSV import via Settings → bank/card transactions stored in `transactions` table
4. `matcher.py` → matches bank transactions to orders by amount + date
5. Export via Settings → CSV reconciliation reports

### Key modules

| Module | Responsibility |
|--------|---------------|
| `retailers/base.py` | `RetailerCollector` ABC — all collectors implement this |
| `retailers/amazon.py` | Amazon collector using `amazon-orders` library |
| `retailers/__init__.py` | `REGISTRY` dict mapping retailer name → collector class |
| `db.py` | SQLite connection, schema migrations, credential helpers |
| `sql/schema.sql` | Source of truth for table DDL |
| `matcher.py` | Amount+date matching; confidence scoring |
| `importers.py` | CSV transaction import with upsert logic |
| `exporter.py` | CSV report generation |
| `api.py` | FastAPI server; all endpoints; thread-safe sync jobs |
| `actual_sync.py` | Optional sync to Actual Budget (`pip install -e ".[actual]"`) |

### Database

SQLite at `data/amazon_spending.sqlite3`. Key tables: `orders`, `order_items`, `retailer_transactions`, `retailer_credentials` (email/password/otp_secret), `transactions` (imported bank data), `matches`, `budget_categories`, `budget_subcategories`, `actual_budget_config`, `retailer_import_runs`.

All retailer-specific tables have a `retailer` column (multi-retailer ready).

### Amazon auth

Credentials (email, password, optional OTP secret) are stored in `retailer_credentials` and entered via the Settings page. The `amazon-orders` library handles login and 2FA automatically using these credentials. No browser profile / Playwright required.

### Adding a new retailer

1. Create `retailers/<name>.py` implementing `RetailerCollector` from `retailers/base.py`
2. Register it in `retailers/__init__.py` `REGISTRY`
3. The `collect()` method signature: `conn, output_dir, *, start_date, end_date, order_limit, should_abort, known_order_ids`

### Frontend pages

React 18 + Vite + React Router + TanStack Table + Tailwind CSS. API at `http://localhost:8000`.

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — sync control, DB status |
| `/orders` | Order history |
| `/transactions` | Retailer payment transactions |
| `/items` | Line items |
| `/reports` | Monthly analytics |
| `/admin` | Budget categories |
| `/settings` | Amazon credentials, CSV import/export, Actual Budget config |

## Configuration

- Line length: 120 (ruff)
- Ruff rules: E, F (ignoring E501, E402, F401)
- Mypy target: Python 3.12
- Pytest testpaths: `tests/`
