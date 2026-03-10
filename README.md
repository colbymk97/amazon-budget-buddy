# amazon_spending

Local-first tooling to collect and store personal Amazon order history in SQLite.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

Initialize database:

```bash
python -m amazon_spending init-db
```

Collect Amazon orders (headless by default, auto-falls back to headed for auth/MFA):

```bash
python -m amazon_spending collect-amazon --order-limit 100 --max-pages 20
```

Parse previously saved raw HTML into the DB without scraping (test run):

```bash
python -m amazon_spending collect-amazon --test-run --order-limit 100
```

Optionally target a specific saved run directory:

```bash
python -m amazon_spending collect-amazon --test-run --saved-run-dir data/raw/amazon/20260216_081306
```

Open local viewer:

```bash
python -m amazon_spending view
```

## New UI (React + API)

Run local API:

```bash
uvicorn amazon_spending.api:app --reload --host 127.0.0.1 --port 8000
```

Run React frontend:

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL: `http://127.0.0.1:5173`  
API default URL: `http://127.0.0.1:8000`

Set API base if needed:

```bash
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

### How Incremental Import Decides How Far To Scan

The dashboard "Import New Data" flow uses a targeted incremental scan instead of blindly walking a fixed number of pages.

- It first looks up the most recent imported order date in SQLite.
- It also loads a small set of the most recently imported order IDs (currently the latest 30).
- The scraper starts near the top of Amazon's order history and keeps collecting listing pages until it sees one of those already-known order IDs again.
- That overlap is treated as the handoff point: once we have reached orders we already imported, the scraper stops going deeper and then fetches details for the newly discovered orders in that window.
- A small date overlap is still applied (`start_date` is backed up by a couple of days) so the importer can safely re-read borderline orders and reconcile updates.
- There is still a safety page cap to avoid runaway scans if Amazon changes the page structure, but the normal stop condition is overlap with known orders, not the cap.
- If headless mode loads the shell of the page but does not surface usable order data, the API retries once in a visible browser window using the same persistent profile.

## Viewer

- URL: `http://127.0.0.1:8501`
- Filter by date range and text (order ID or item text).
- Browse orders and inspect item/shipment details.

## Optional: Import bank transactions (stored only)

```bash
python -m amazon_spending import-transactions --csv data/transactions.csv --account-id chase-freedom
```

This currently only stores transactions in SQLite for future export/reconciliation features.

## Notes

- Database defaults to `./data/amazon_spending.sqlite3`.
- `collect-amazon` stores raw HTML snapshots under `data/raw/amazon/<timestamp>/`.
- End of every collect run performs DB reconciliation and prints inserted/updated/unchanged counts.
- Incremental API imports are overlap-driven: they stop when the listing reaches orders already present in the local database, then report how many new orders were found since the last imported order date.
- Collector also pulls related Amazon payment transactions and stores:
  - `amazon_transactions` (per-order Amazon transaction records)
  - `order_item_transactions` (item-to-transaction links)
