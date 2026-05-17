# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (dev mode)
pip install -e ".[dev,actual]"
playwright install chromium

# CLI subcommands (scriptable)
amazon-spending --help
amazon-spending init-db
amazon-spending login --retailer amazon
amazon-spending collect --retailer amazon --stop-on-known
amazon-spending actual-sync
amazon-spending export
amazon-spending db-status

# TUI (interactive)
amazon-spending tui

# Tests
pytest
pytest tests/test_tui_queries.py

# Lint / type check
ruff check .
mypy .
```

## Architecture

Local-first budget reconciliation tool. Two entry points sharing one SQLite database:

- **CLI** (`amazon_spending.cli`) owns all writes. Scrapes Amazon via Playwright, imports bank/card CSVs, runs Actual Budget syncs, exports CSV reports. Authenticates with a persistent Chromium profile under the app-data dir — first run opens a headed browser, subsequent runs go silent.
- **TUI** (`amazon_spending.tui`) is a Textual app for browsing the same SQLite database and triggering CLI commands inline with live output. `amazon-spending tui` is a CLI subcommand.

There is no web app. There is no separate API server. The TUI is the interactive surface; the CLI is the scriptable surface; both read/write the same SQLite file.

### Data flow

1. `amazon-spending login --retailer amazon` — opens headed browser; user logs in; cookies persisted to the Chromium profile.
2. `amazon-spending collect --retailer amazon [--stop-on-known]` — Playwright scrapes order history and per-order detail / related-transactions pages, parses HTML with regex in `retailers/amazon.py`, reconciles into `orders`, `order_items`, `retailer_transactions`, `shipments`, `order_item_transactions`.
3. `amazon-spending import-transactions --csv ...` — ingests bank/card CSVs into `transactions`.
4. `matcher.py` matches bank transactions to retailer orders by amount + date.
5. `amazon-spending actual-sync` pushes unsynced retailer transactions to Actual Budget.
6. `amazon-spending tui` opens the interactive viewer. The Commands screen lets you re-run any of the above without leaving the TUI.

### Key modules

| Module | Responsibility |
|--------|---------------|
| `cli.py` | argparse CLI; primary scriptable interface |
| `tui/` | Textual app — sidebar + Dashboard / Orders / Transactions / Items / Reports / Commands screens |
| `tui/queries.py` | Read-only DB helpers used by every screen |
| `tui/command_runner.py` | Async subprocess wrapper that streams CLI stdout to a RichLog |
| `retailers/base.py` | `RetailerCollector` ABC, `CollectResult` / `ParsedOrder` / `ParsedItem` / `ParsedRetailerTransaction` dataclasses |
| `retailers/amazon.py` | Playwright + regex Amazon scraper |
| `retailers/__init__.py` | `REGISTRY` dict mapping retailer name → collector instance |
| `db.py` | SQLite connection, schema migrations, retailer-account helpers |
| `sql/schema.sql` | Source of truth for table DDL |
| `matcher.py` | Amount+date matching; confidence scoring |
| `importers.py` | CSV transaction import with upsert logic |
| `exporter.py` | CSV report generation |
| `audit.py` | Compare Amazon listing pages against the local DB without mutating |
| `actual_sync.py` | Optional sync to Actual Budget (`pip install -e ".[actual]"`) |
| `paths.py` | App-data directory + auto-migration of legacy `./data/` |

### Database and persistent state

By default the DB and Playwright profile live under the OS app-data dir:

- macOS:   `~/Library/Application Support/amazon-spending/`
- Linux:   `~/.local/share/amazon-spending/`
- Windows: `%APPDATA%\amazon-spending\`

Inside that directory: `amazon_spending.sqlite3`, `browser_profiles/<retailer>/`, `raw/<retailer>/<timestamp>/`. Set `AMAZON_SPENDING_HOME=/some/path` to override.

Tables: `orders`, `shipments`, `order_items`, `retailer_transactions`, `order_item_transactions`, `transactions`, `matches`, `budget_categories`, `budget_subcategories`, `actual_budget_config`, `retailer_accounts`, `retailer_import_runs`.

`budget_categories` / `budget_subcategories` / `retailer_transactions.budget_*_id` columns are present in the schema but currently **unused**. They'll be populated once an Actual-Budget category sync (and possibly AI auto-categorization) is built.

### Amazon auth

Playwright with a persistent Chromium profile under the app-data dir at `browser_profiles/amazon/`. First `collect` or `login` opens a headed browser for the user to sign in (CAPTCHA / 2FA handled manually). Profile cookies persist, so subsequent runs go fully headless. No credentials are stored in the database.

### Adding a new retailer

1. Create `retailers/<name>.py` implementing `RetailerCollector` from `retailers/base.py`.
2. Register it in `retailers/__init__.py` `REGISTRY`.
3. The `collect()` method signature: `conn, output_dir, *, start_date, end_date, order_limit, should_abort, known_order_ids` (concrete collectors may accept additional kwargs).

### TUI screens

| Screen | Hotkey | Purpose |
|--------|--------|---------|
| Dashboard | 1 | Retailer counts, date range, last import status |
| Orders | 2 | Filterable orders list; row-enter opens an items + transactions modal |
| Transactions | 3 | Filterable retailer transactions list |
| Items | 4 | Filterable order items list |
| Reports | 5 | Month picker → net spend, gross totals, counts, top-30 orders |
| Commands | 6 | Buttons to run login / collect / audit / actual-sync / export / db-status with live log |

## Configuration

- Line length: 120 (ruff)
- Ruff rules: E, F (ignoring E501, E402, F401)
- Mypy target: Python 3.13
- Pytest testpaths: `tests/`
