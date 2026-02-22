You are modernizing the UI for a local-first Amazon spending analyzer project.

Current state:
- Backend/data pipeline is Python.
- Data is stored in SQLite at `data/amazon_spending.sqlite3`.
- Existing Streamlit UI should be replaced (or deprecated) by a React frontend.
- Tables/entities in DB include:
  - `orders` (with `order_url`)
  - `amazon_transactions`
  - `order_items`
  - join/link tables like `order_item_transactions`.

Goal:
Build a production-style UI with React that supports high-density data exploration and drilldowns.

Requirements:
1. Frontend framework:
   - React (Vite + TypeScript preferred).
   - Use a robust table library (TanStack Table preferred) with:
     - sorting
     - filtering (global + column)
     - pagination or virtualized scrolling
     - column show/hide and resizing if practical.

2. Navigation and pages:
   - Top navigation (no sidebar-heavy layout).
   - Pages:
     - Home dashboard
     - Orders view
     - Transactions view
     - Order Items view
   - Detail drilldown pages:
     - Order detail page: show order info + associated transactions + associated items.
     - Transaction detail page: show transaction info + parent order + linked items.
     - Item detail page: show item info + parent order + linked transactions.
   - All entities should link to each other where relationships exist.

3. Data display:
   - Show as much table data as practical on screen.
   - Include `order_url` wherever available and render as clickable link.
   - Format currency cleanly from cents.
   - Preserve IDs (`order_id`, `amazon_txn_id`, `item_id`) visibly for debugging.

4. Backend/API:
   - Keep existing collector/parser and SQLite model.
   - Add a lightweight API layer (FastAPI preferred) to serve frontend data.
   - Endpoints should support:
     - list + filters for orders, transactions, order_items
     - detail by ID
     - related records by ID.
   - Must be local-first and easy to run in development.

5. UX expectations:
   - Fast interactions and clear hierarchy.
   - Avoid toy/demo styling; use a clean, intentional app layout.
   - Keep it desktop-first but usable on mobile.

6. Deliverables:
   - New `frontend/` React app.
   - API server files and routes.
   - Updated README with run instructions for both API and frontend.
   - Minimal smoke checks to verify pages load and data round-trips from SQLite.

7. Non-goals:
   - Do not rewrite collector logic unless required for API compatibility.
   - Do not remove raw scraping/test-run functionality.

Acceptance criteria:
- I can open the new React app, browse Orders/Transactions/Order Items tables with sorting/filtering.
- Clicking a row opens a dedicated detail page.
- I can navigate between linked entities from detail pages.
- `order_url` is displayed when present.
- The app reads live data from the existing SQLite DB through the API.
