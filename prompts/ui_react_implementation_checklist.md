UI React Implementation Checklist

1. Backend API
- Add FastAPI app over existing SQLite DB (`data/amazon_spending.sqlite3`).
- Implement list + detail endpoints for:
  - orders
  - amazon_transactions
  - order_items
- Implement relationship endpoints:
  - order -> transactions/items
  - transaction -> parent order/items
  - item -> parent order/transactions
- Include `order_url` in order payloads.
- Add CORS for local frontend dev.

2. Frontend App
- Create Vite + React + TypeScript app under `frontend/`.
- Add top navigation:
  - Home
  - Orders
  - Transactions
  - Order Items
- Implement table views with sorting/filtering using TanStack Table.
- Make rows clickable and route to detail pages.

3. Detail Pages
- Order detail:
  - order metadata
  - associated transactions table
  - associated items table
  - clickable `order_url` if present
- Transaction detail:
  - transaction metadata
  - parent order block/link
  - associated items
- Item detail:
  - item metadata
  - parent order block/link
  - associated transactions

4. Data + Formatting
- Show cents as formatted USD.
- Keep IDs visible (`order_id`, `amazon_txn_id`, `item_id`).
- Preserve dense table layout to maximize visible data.

5. Docs + Run
- Update README with:
  - API run command
  - frontend run command
  - expected local ports
- Keep existing collector/test-run workflow unchanged.

6. Smoke Validation
- API responds for list + detail endpoints.
- Frontend pages render and navigate.
- Cross-links between entities work.
