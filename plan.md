# Multi-Retailer Refactor Plan

## Goal

Introduce a retailer adapter architecture so Amazon, Target, and future retailers
all plug into the same collection pipeline and shared SQLite schema. The CLI
exposes `collect --retailer amazon|target`; the DB stores all retailers in a
unified `retailer_transactions` table.

---

## New Directory Layout

```
amazon_spending/
  retailers/
    __init__.py        # REGISTRY dict mapping retailer ID → collector class
    base.py            # RetailerCollector ABC + shared dataclasses
    amazon.py          # Amazon collector (content of current collector.py)
    target.py          # Target collector stub
  collector.py         # → thin shim: re-exports collect_amazon for api.py compat
  db.py                # + _migrate_to_multi_retailer() migration step
  sql/schema.sql       # updated: retailer_transactions, retailer_txn_id, retailer col
  cli.py               # collect --retailer amazon|target
  api.py               # updated imports + SQL + renamed path params
  exporter.py          # no changes needed
  matcher.py           # check for any amazon_transactions references
  importers.py         # check for any amazon_transactions references
```

---

## Step-by-step Changes

### 1. `amazon_spending/retailers/base.py` (new)

Move shared dataclasses out of `collector.py` and into this module:
- `CollectResult`
- `ParsedOrder`
- `ParsedItem`
- `ParsedRetailerTransaction` (rename from `ParsedAmazonTransaction`, add `retailer: str` field)

Define the abstract base:
```python
class RetailerCollector(ABC):
    RETAILER_ID: ClassVar[str]

    @abstractmethod
    def collect(
        self,
        conn: sqlite3.Connection,
        output_dir: Path,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        order_limit: int | None = None,
        max_pages: int | None = None,
        headless: bool = True,
        user_data_dir: Path | None = None,
        test_run: bool = False,
        saved_run_dir: Path | None = None,
        allow_interactive_auth: bool = True,
        should_abort: Callable[[], bool] | None = None,
        stop_when_before_start_date: bool = False,
        known_order_ids: list[str] | None = None,
        overlap_match_threshold: int = 1,
    ) -> CollectResult: ...
```

### 2. `amazon_spending/retailers/amazon.py` (new — move from collector.py)

- Copy full content of `collector.py`
- Replace `ParsedAmazonTransaction` with `ParsedRetailerTransaction` (import from base)
- Wrap the module-level `collect_amazon()` function inside `class AmazonCollector(RetailerCollector):`
  with `RETAILER_ID = "amazon"` and a `collect()` method that delegates to the
  existing function body
- All SQL stays the same but uses renamed DB columns (`retailer_txn_id`, `retailer_transactions`)
- `_reconcile_amazon_transactions()` → `_reconcile_retailer_transactions()`
  inserts `retailer = 'amazon'` on every row

### 3. `amazon_spending/retailers/target.py` (new — stub)

```python
class TargetCollector(RetailerCollector):
    RETAILER_ID = "target"

    def collect(self, conn, output_dir, **kwargs) -> CollectResult:
        raise NotImplementedError(
            "Target scraping is not yet implemented. "
            "Contributions welcome — see retailers/base.py for the interface."
        )
```

### 4. `amazon_spending/retailers/__init__.py` (new)

```python
from .base import RetailerCollector, CollectResult
from .amazon import AmazonCollector
from .target import TargetCollector

REGISTRY: dict[str, RetailerCollector] = {
    "amazon": AmazonCollector(),
    "target": TargetCollector(),
}
```

### 5. `amazon_spending/sql/schema.sql` (modify)

Rename for fresh installs:
- `amazon_transactions` → `retailer_transactions`
- `amazon_txn_id` → `retailer_txn_id`
- `order_items.amazon_transaction_id` → `order_items.retailer_transaction_id`
- `order_item_transactions.amazon_txn_id` → `order_item_transactions.retailer_txn_id`
- Add `retailer TEXT NOT NULL DEFAULT 'amazon'` to `orders`
- Add `retailer TEXT NOT NULL DEFAULT 'amazon'` to `retailer_transactions`
- Update all index names accordingly

### 6. `amazon_spending/db.py` (modify)

Add `_migrate_to_multi_retailer(conn)` called inside `init_db()` before the schema script:

```python
def _migrate_to_multi_retailer(conn: sqlite3.Connection) -> None:
    """One-time migration: rename amazon_* → retailer_* and add retailer column."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}

    # 1. Rename the table
    if "amazon_transactions" in tables and "retailer_transactions" not in tables:
        conn.execute("ALTER TABLE amazon_transactions RENAME TO retailer_transactions")

    # 2. Rename primary key column on retailer_transactions
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(retailer_transactions)")}
    if cols and "amazon_txn_id" in cols:
        conn.execute("ALTER TABLE retailer_transactions RENAME COLUMN amazon_txn_id TO retailer_txn_id")

    # 3. Add retailer column to retailer_transactions
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(retailer_transactions)")}
    if cols and "retailer" not in cols:
        conn.execute("ALTER TABLE retailer_transactions ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'")

    # 4. Rename FK column in order_items
    item_cols = {r["name"] for r in conn.execute("PRAGMA table_info(order_items)")}
    if item_cols and "amazon_transaction_id" in item_cols:
        conn.execute("ALTER TABLE order_items RENAME COLUMN amazon_transaction_id TO retailer_transaction_id")

    # 5. Rename FK/PK column in order_item_transactions
    oit_cols = {r["name"] for r in conn.execute("PRAGMA table_info(order_item_transactions)")}
    if oit_cols and "amazon_txn_id" in oit_cols:
        conn.execute("ALTER TABLE order_item_transactions RENAME COLUMN amazon_txn_id TO retailer_txn_id")

    # 6. Add retailer column to orders
    order_cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}
    if order_cols and "retailer" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN retailer TEXT NOT NULL DEFAULT 'amazon'")

    conn.commit()
```

Update `_ensure_columns()` to reference the new column/table names.

### 7. `amazon_spending/cli.py` (modify)

Replace `collect-amazon` subcommand with `collect`:

```
amazon-spending collect --retailer amazon [options]
amazon-spending collect --retailer target [options]
```

- `--retailer` becomes a required flag with `choices=list(REGISTRY)`
- All other flags stay the same (they're passed through to the retailer adapter)
- Raw HTML output directory defaults to `data/raw/{retailer}` (retailer-namespaced)
- Browser profile directory defaults to `data/raw/{retailer}/browser_profile`
- `_handle_collect` looks up `REGISTRY[args.retailer]` and calls `.collect()`

Keep `collect-amazon` as a hidden alias (for backward compat) that delegates
to `collect --retailer amazon`.

### 8. `amazon_spending/api.py` (modify)

- Change import: `from .retailers import REGISTRY` (remove `from .collector import collect_amazon`)
- `_run_sync_job()`: call `REGISTRY["amazon"].collect(...)` — behavior identical
- `DEFAULT_RAW_OUTDIR` → `PROJECT_ROOT / "data/raw/amazon"` (unchanged, amazon-specific path stays)
- SQL: all references to `amazon_transactions` → `retailer_transactions`,
  `amazon_txn_id` → `retailer_txn_id`, `amazon_transaction_id` → `retailer_transaction_id`
- Path parameter `{amazon_txn_id}` → `{retailer_txn_id}` in all endpoint definitions
- `_construct_order_url()`: check `retailer` field and build correct URL per retailer

### 9. `amazon_spending/collector.py` (modify — thin shim)

Preserve backward compat for any external scripts that import from `collector`:

```python
# Backward-compat shim — import from the new location
from .retailers.amazon import AmazonCollector
from .retailers.base import CollectResult, ParsedOrder, ParsedItem, ParsedRetailerTransaction as ParsedAmazonTransaction

def collect_amazon(conn, output_dir, **kwargs) -> CollectResult:
    return AmazonCollector().collect(conn, output_dir, **kwargs)
```

### 10. `README.md` (update)

- Document `collect --retailer amazon` replacing `collect-amazon`
- Note backward-compat alias
- Add section on adding new retailer adapters

---

## What Does NOT Change

- `exporter.py` — queries only `matches`, `transactions`, `order_items`; no retailer-specific tables
- `matcher.py` — similarly, only references generic tables; verify and leave alone
- `importers.py` — only touches `transactions` table
- `webapp.py` — legacy viewer; update SQL if it references `amazon_transactions`
- Frontend (`frontend/`) — the React UI already uses the API; only needs updates
  if the API response fields change (they will for `amazon_txn_id` → `retailer_txn_id`)
- All budget category/subcategory functionality — fully generic already

---

## Frontend Impact

The React types in `frontend/src/types.ts` likely reference `amazon_txn_id`. After
the API rename to `retailer_txn_id`, those types need updating. This is a separate
contained change within `types.ts` and `api.ts`.

---

## Migration Safety

- All `ALTER TABLE ... RENAME` operations require SQLite ≥ 3.25 (Python 3.6+ ships ≥ 3.28)
- Migration is guarded by column/table existence checks — idempotent, safe to run twice
- Existing data is fully preserved; only names change
- If a user has no DB yet, the schema creates the new names directly

---

## File Change Summary

| File | Action |
|------|--------|
| `retailers/__init__.py` | Create |
| `retailers/base.py` | Create |
| `retailers/amazon.py` | Create (move from collector.py) |
| `retailers/target.py` | Create (stub) |
| `sql/schema.sql` | Modify (rename tables/cols, add retailer col) |
| `db.py` | Modify (add migration) |
| `collector.py` | Modify (thin shim) |
| `cli.py` | Modify (collect --retailer) |
| `api.py` | Modify (imports, SQL, path params) |
| `webapp.py` | Modify (SQL, if any amazon_transactions refs) |
| `README.md` | Modify |
| `frontend/src/types.ts` | Modify (retailer_txn_id) |
| `frontend/src/api.ts` | Modify (retailer_txn_id) |
| `frontend/src/pages/*.tsx` | Modify (any amazon_txn_id field refs) |
| `matcher.py` | Verify (likely no changes) |
| `importers.py` | Verify (likely no changes) |
| `exporter.py` | No change |
| `tests/test_sync_logic.py` | Verify/update imports |
