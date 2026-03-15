from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .db import (
    DEFAULT_DB_PATH,
    RetailerAccountMismatchError,
    connect,
    db_status_payload,
    ensure_retailer_account,
    get_retailer_account,
    init_db,
    recent_retailer_order_ids,
    record_retailer_import_run,
)
from .exporter import export_reports
from .importers import import_transactions_csv
from .retailers import REGISTRY

VERSION = "0.1.0"
_RETAILER_CHOICES = sorted(REGISTRY.keys())

# ---------------------------------------------------------------------------
# Shared formatter: wider help columns for long flag names
# ---------------------------------------------------------------------------

class _Formatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=36, width=90)


# ---------------------------------------------------------------------------
# Per-command epilog examples
# ---------------------------------------------------------------------------

_INIT_DB_EPILOG = """
examples:
  # Initialize with the default database path
  amazon-spending init-db

  # Use a custom database file
  amazon-spending --db ~/my-data.sqlite3 init-db
"""

_DB_STATUS_EPILOG = """
examples:
  # Show counts, account bindings, and latest import timestamps
  amazon-spending db-status

  # Read a non-default database
  amazon-spending --db ~/my-data.sqlite3 db-status
"""

_COLLECT_EPILOG = """
examples:
  # Collect the most recent 50 Amazon orders (headless, auto-auth fallback)
  amazon-spending collect --retailer amazon --order-limit 50

  # Collect a specific date range
  amazon-spending collect --retailer amazon --start-date 2024-01-01 --end-date 2024-06-30

  # Force a visible browser window (useful for first-time login / MFA)
  amazon-spending collect --retailer amazon --headed --order-limit 20

  # Re-parse previously saved HTML without launching a browser
  amazon-spending collect --retailer amazon --test-run

  # Re-parse a specific saved snapshot directory
  amazon-spending collect --retailer amazon --saved-run-dir data/raw/amazon/20260216_081306

  # Fastest incremental sync — stop when known orders are encountered
  amazon-spending collect --retailer amazon --stop-on-known

  # Machine-readable JSON output
  amazon-spending collect --retailer amazon --order-limit 10 --json

notes:
  - Raw HTML is saved under --outdir/<timestamp>/ before parsing.
  - Headless mode falls back automatically when the retailer requires
    interactive login or MFA.
  - --saved-run-dir implies --test-run automatically.
  - Deprecated alias: collect-amazon (same as collect --retailer amazon)
"""

_IMPORT_EPILOG = """
required CSV columns:
  transaction_id   Unique identifier for the bank/card transaction
  posted_date      ISO date the transaction posted (YYYY-MM-DD)
  amount           Transaction amount in dollars (e.g. 42.99 or -12.50)
  merchant_raw     Raw merchant name as it appears on the statement

examples:
  # Import from a Copilot / Chase CSV export
  amazon-spending import-transactions --csv data/transactions.csv

  # Tag rows with an account label for multi-card households
  amazon-spending import-transactions --csv data/amex.csv --account-id amex-gold

  # Emit a JSON summary instead of plain text
  amazon-spending import-transactions --csv data/transactions.csv --json
"""

_EXPORT_EPILOG = """
output files:
  report_transaction_itemized.csv   Each transaction mapped to its matched order items
  report_unmatched.csv              Transactions with no order match
  report_monthly_summary.csv        Monthly spending totals grouped by essential flag

examples:
  # Export to the default directory (data/exports/)
  amazon-spending export

  # Export to a custom directory
  amazon-spending export --outdir ~/reports/2024
"""

_LOGIN_EPILOG = """
examples:
  # Open a browser window and log in to Amazon interactively
  amazon-spending login --retailer amazon

  # Check silently whether the stored session is still valid (exit 0 = ok)
  amazon-spending login --retailer amazon --check

  # Use a custom browser profile location
  amazon-spending login --retailer amazon --user-data-dir /path/to/profile

notes:
  - Amazon requires MFA, so login is always interactive (no password flags).
  - The browser reuses the same persistent Chromium profile as 'collect', so
    logging in here means future collect runs will not need to prompt.
  - --check is silent and suitable for scripting: exit 0 = logged in,
    exit 1 = login required.
"""

_ACTUAL_SYNC_EPILOG = """
examples:
  # Configure Actual Budget once and store settings in the local DB
  amazon-spending actual-configure --base-url http://localhost:5006 --file "My Budget"

  # Preview matches without writing any changes
  amazon-spending actual-sync --dry-run

  # Sync all unsynced retailer transactions to Actual Budget
  amazon-spending actual-sync

  # Machine-readable output
  amazon-spending actual-sync --json

notes:
  - Configure Actual once with actual-configure; actual-sync reuses that stored config.
  - Only transactions with actual_synced_at IS NULL are processed.
  - Each transaction is matched by exact amount (±$0) within ±3 days of txn_date.
  - The first matching Actual transaction has its notes appended with the
    Amazon order ID and allocated line-items.
  - Synced transactions are never re-processed.
"""

_AUDIT_EPILOG = """
modes:
  full    Scan from today back to the oldest locally-imported order date.
          Finds every order that exists on Amazon in that window but is
          absent from the local database.  Alias: from-first-transaction

  latest  Scan from today until the first locally-known order is encountered.
          Finds orders that appeared after the most recent collect run.
          Alias: from-latest-transaction

examples:
  # Full audit — compare all Amazon history against local DB
  amazon-spending audit --retailer amazon --mode full

  # Same via alias
  amazon-spending from-first-transaction --retailer amazon

  # Latest audit — check for new orders since last collect
  amazon-spending audit --retailer amazon --mode latest
  amazon-spending from-latest-transaction --retailer amazon

  # Force a visible browser window (useful if session needs re-auth)
  amazon-spending audit --retailer amazon --mode full --headed

  # Machine-readable output
  amazon-spending audit --retailer amazon --mode latest --json

notes:
  - Only listing pages are fetched.  No order detail or payment pages are
    opened, so the audit is fast and leaves the database unchanged.
  - Full audit stops after 3 consecutive orders older than the anchor date.
  - Latest audit stops the moment any locally-known order ID appears on a
    listing page.
  - Missing orders are reported but NOT automatically imported.  Run
    'collect' with appropriate --start-date / --end-date to pull them in.
"""

_ACTUAL_CONFIGURE_EPILOG = """
examples:
  # Initial setup (password will be prompted if omitted)
  amazon-spending actual-configure --base-url http://localhost:5006 --file "My Budget"

  # Validate the settings before saving them
  amazon-spending actual-configure --base-url http://localhost:5006 --file "My Budget" --test-connection

  # Set or change the account filter
  amazon-spending actual-configure --account-name "Chase Sapphire"

  # Remove the account filter and search all Actual accounts
  amazon-spending actual-configure --clear-account-name

  # Show the stored configuration without revealing the password
  amazon-spending actual-configure --show
"""


# ---------------------------------------------------------------------------
# Shared collect flags — used by both `collect` and the legacy `collect-amazon`
# ---------------------------------------------------------------------------

def _add_collect_args(p: argparse.ArgumentParser) -> None:
    """Attach all collect flags to a parser (shared between collect and collect-amazon)."""

    # Date / scope
    p.add_argument(
        "--start-date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Earliest order date to collect (inclusive)",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Latest order date to collect (inclusive)",
    )
    p.add_argument(
        "--order-limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of orders to collect per run",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Maximum listing pages to traverse "
            "(default: derived from --order-limit when provided)"
        ),
    )

    # Browser options
    browser_group = p.add_argument_group("browser options")
    browser_group.add_argument(
        "--headed",
        action="store_true",
        help="Force a visible browser window (default: headless with auto-auth fallback)",
    )
    browser_group.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Persistent browser profile directory for session cookies "
            "(default: data/raw/<retailer>/browser_profile)"
        ),
    )

    # Storage / offline options
    storage_group = p.add_argument_group("storage options")
    storage_group.add_argument(
        "--outdir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory for raw HTML snapshots (default: data/raw/<retailer>)",
    )
    storage_group.add_argument(
        "--test-run",
        action="store_true",
        help="Parse a previously saved HTML snapshot without launching the browser",
    )
    storage_group.add_argument(
        "--saved-run-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Specific snapshot directory to parse (implies --test-run; "
            "default: latest under --outdir)"
        ),
    )

    # Incremental sync
    sync_group = p.add_argument_group("incremental sync options")
    sync_group.add_argument(
        "--stop-on-known",
        action="store_true",
        help=(
            "Stop scanning as soon as a previously imported order ID is encountered "
            "(fastest for incremental syncs)"
        ),
    )

    # Output
    p.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print results as a JSON object instead of plain text",
    )


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazon-spending",
        description=(
            "amazon-spending — local-first retailer order collector and budget tool.\n"
            "\n"
            "Scrapes order history from supported retailers into a local SQLite database,\n"
            "imports bank/card transactions, and exports reconciliation reports. All data\n"
            "stays on your machine — no cloud services required.\n"
            "\n"
            f"supported retailers: {', '.join(_RETAILER_CHOICES)}"
        ),
        formatter_class=_Formatter,
        epilog=(
            "Run 'amazon-spending <command> --help' for detailed help on any command.\n"
            "\n"
            "quick start:\n"
            "  amazon-spending init-db\n"
            "  amazon-spending collect --retailer amazon --order-limit 100\n"
            "  amazon-spending db-status\n"
        ),
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        metavar="PATH",
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"amazon-spending {VERSION}",
    )

    sub = parser.add_subparsers(dest="command", required=True, title="commands")

    # ------------------------------------------------------------------ init-db
    sub.add_parser(
        "init-db",
        help="Initialize or migrate the SQLite schema",
        description=(
            "Creates the SQLite database and applies the full schema.\n"
            "Safe to run on an existing database — missing tables and columns\n"
            "are added without touching existing data."
        ),
        formatter_class=_Formatter,
        epilog=_INIT_DB_EPILOG,
    )

    sub.add_parser(
        "db-status",
        help="Summarize retailer counts, account bindings, and last import times",
        description=(
            "Shows a quick database health summary by retailer, including order and\n"
            "retailer transaction counts, the account bound to this database, and the\n"
            "most recent recorded import timestamp/status."
        ),
        formatter_class=_Formatter,
        epilog=_DB_STATUS_EPILOG,
    ).add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print results as a JSON object instead of plain text",
    )

    # ----------------------------------------------------------------- collect
    p_collect = sub.add_parser(
        "collect",
        help="Scrape retailer order history into the local database",
        description=(
            "Launches a browser to collect orders, shipments, line items, and\n"
            "payment transactions for the specified retailer, then reconciles them\n"
            "into the local SQLite database.\n"
            "\n"
            f"supported retailers: {', '.join(_RETAILER_CHOICES)}"
        ),
        formatter_class=_Formatter,
        epilog=_COLLECT_EPILOG,
    )
    p_collect.add_argument(
        "--retailer",
        required=True,
        choices=_RETAILER_CHOICES,
        metavar="NAME",
        help=f"Retailer to collect from: {{{', '.join(_RETAILER_CHOICES)}}}",
    )
    _add_collect_args(p_collect)

    # -------------------------------------------- collect-amazon (legacy alias)
    p_collect_amazon = sub.add_parser(
        "collect-amazon",
        help="[deprecated] Alias for: collect --retailer amazon",
        description="Deprecated alias for 'collect --retailer amazon'. Use collect instead.",
        formatter_class=_Formatter,
        epilog=_COLLECT_EPILOG,
    )
    _add_collect_args(p_collect_amazon)

    # ------------------------------------------------------------------- login
    p_login = sub.add_parser(
        "login",
        help="Authenticate with a retailer by logging in via a browser window",
        description=(
            "Opens a Chromium browser window so you can log in to the retailer\n"
            "interactively (including MFA). The session is saved in a persistent\n"
            "browser profile so future 'collect' runs work without prompting.\n"
            "\n"
            "Use --check to test silently whether the stored session is still valid."
        ),
        formatter_class=_Formatter,
        epilog=_LOGIN_EPILOG,
    )
    p_login.add_argument(
        "--retailer",
        required=True,
        choices=_RETAILER_CHOICES,
        metavar="NAME",
        help=f"Retailer to authenticate with: {{{', '.join(_RETAILER_CHOICES)}}}",
    )
    p_login.add_argument(
        "--check",
        action="store_true",
        help=(
            "Check silently whether the stored session is valid (headless). "
            "Exits 0 if logged in, 1 if login is required."
        ),
    )
    p_login.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Persistent browser profile directory "
            "(default: data/raw/<retailer>/browser_profile)"
        ),
    )
    p_login.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Seconds to wait for manual login before giving up (default: 300)",
    )
    p_login.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print result as a JSON object instead of plain text",
    )

    # -------------------------------------------------------------------- audit
    def _add_audit_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--retailer",
            default="amazon",
            choices=_RETAILER_CHOICES,
            metavar="NAME",
            help=f"Retailer to audit (default: amazon): {{{', '.join(_RETAILER_CHOICES)}}}",
        )
        p.add_argument(
            "--headed",
            action="store_true",
            help="Force a visible browser window (default: headless)",
        )
        p.add_argument(
            "--user-data-dir",
            type=Path,
            default=None,
            metavar="PATH",
            help="Persistent browser profile directory (default: data/raw/<retailer>/browser_profile)",
        )
        p.add_argument(
            "--json",
            dest="output_json",
            action="store_true",
            help="Print results as a JSON object instead of plain text",
        )

    p_audit = sub.add_parser(
        "audit",
        help="Compare Amazon order history against the local database",
        description=(
            "Scans Amazon order listing pages and compares the results against the\n"
            "local database, reporting any orders present on Amazon that have not\n"
            "been imported locally.  Only listing pages are fetched — the audit is\n"
            "fast and makes no changes to the database.\n"
            "\n"
            "Two modes:\n"
            "  full    Scan from today back to the oldest locally-imported order.\n"
            "  latest  Scan from today until the most-recent local order is found."
        ),
        formatter_class=_Formatter,
        epilog=_AUDIT_EPILOG,
    )
    p_audit.add_argument(
        "--mode",
        required=True,
        choices=["full", "latest"],
        help="'full' (from first transaction) or 'latest' (from last transaction)",
    )
    _add_audit_args(p_audit)

    # Alias: from-first-transaction → audit --mode full
    p_from_first = sub.add_parser(
        "from-first-transaction",
        help="[alias] Full audit: scan Amazon from today back to the oldest local order",
        description="Alias for: audit --mode full\n\nFinds every order on Amazon since your oldest imported order that is missing from the local database.",
        formatter_class=_Formatter,
        epilog=_AUDIT_EPILOG,
    )
    _add_audit_args(p_from_first)

    # Alias: from-latest-transaction → audit --mode latest
    p_from_latest = sub.add_parser(
        "from-latest-transaction",
        help="[alias] Latest audit: scan Amazon for new orders since the last import",
        description="Alias for: audit --mode latest\n\nFinds orders that appeared on Amazon after your most recent collect run.",
        formatter_class=_Formatter,
        epilog=_AUDIT_EPILOG,
    )
    _add_audit_args(p_from_latest)

    # ------------------------------------------------------ import-transactions
    p_import = sub.add_parser(
        "import-transactions",
        help="Import bank/card transactions from a CSV file",
        description=(
            "Reads a CSV file of bank or credit-card transactions and upserts\n"
            "them into the local database for future reconciliation with retailer\n"
            "orders. Existing rows are updated on conflict; no duplicates are\n"
            "created for the same transaction_id."
        ),
        formatter_class=_Formatter,
        epilog=_IMPORT_EPILOG,
    )
    p_import.add_argument(
        "--csv",
        type=Path,
        required=True,
        metavar="PATH",
        help="Path to the transactions CSV file (required)",
    )
    p_import.add_argument(
        "--account-id",
        type=str,
        default=None,
        metavar="ID",
        help="Optional label to tag rows with (e.g. 'chase-freedom', 'amex-gold')",
    )
    p_import.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print results as a JSON object instead of plain text",
    )

    # ------------------------------------------------------------------ export
    p_export = sub.add_parser(
        "export",
        help="Export reconciliation reports to CSV files",
        description=(
            "Generates three CSV reports from the local database:\n"
            "\n"
            "  • report_transaction_itemized.csv — each transaction matched\n"
            "    to its retailer order line items\n"
            "  • report_unmatched.csv — transactions with no order match\n"
            "  • report_monthly_summary.csv — monthly totals by essential flag"
        ),
        formatter_class=_Formatter,
        epilog=_EXPORT_EPILOG,
    )
    p_export.add_argument(
        "--outdir",
        type=Path,
        default=Path("data/exports"),
        metavar="PATH",
        help="Directory to write report files into (default: data/exports)",
    )
    p_export.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print a JSON summary of output file paths instead of plain text",
    )

    # ------------------------------------------------------- actual-configure
    p_actual_config = sub.add_parser(
        "actual-configure",
        help="Store Actual Budget connection settings in the local database",
        description=(
            "Saves the Actual Budget base URL, password, budget file name, and optional\n"
            "account filter in the SQLite database so actual-sync can run without a\n"
            "config file or repeated CLI flags."
        ),
        formatter_class=_Formatter,
        epilog=_ACTUAL_CONFIGURE_EPILOG,
    )
    p_actual_config.add_argument("--base-url", type=str, default=None, metavar="URL", help="Actual server base URL")
    p_actual_config.add_argument("--password", type=str, default=None, metavar="TEXT", help="Actual password")
    p_actual_config.add_argument("--file", type=str, default=None, metavar="NAME", help="Actual budget file name")
    p_actual_config.add_argument(
        "--account-name",
        type=str,
        default=None,
        metavar="NAME",
        help="Optional Actual account name to restrict matching",
    )
    p_actual_config.add_argument(
        "--clear-account-name",
        action="store_true",
        help="Remove any stored Actual account filter",
    )
    p_actual_config.add_argument(
        "--show",
        action="store_true",
        help="Show the stored Actual configuration without revealing the password",
    )
    p_actual_config.add_argument(
        "--test-connection",
        action="store_true",
        help="Validate the Actual server, budget file, and optional account filter before saving",
    )
    p_actual_config.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print results as a JSON object instead of plain text",
    )

    # ------------------------------------------------------------ actual-sync
    p_actual = sub.add_parser(
        "actual-sync",
        help="Push unsynced retailer transactions to an Actual Budget instance",
        description=(
            "Matches each unsynced retailer transaction to an Actual Budget\n"
            "transaction by exact amount and date (±3 days), then appends the\n"
            "Amazon order ID and line-items to that transaction's notes field.\n"
            "\n"
            "Requires actualpy: pip install actualpy\n"
            "Requires prior setup via: amazon-spending actual-configure"
        ),
        formatter_class=_Formatter,
        epilog=_ACTUAL_SYNC_EPILOG,
    )
    p_actual.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matches without writing anything to Actual Budget or the local DB",
    )
    p_actual.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print results as a JSON object instead of plain text",
    )

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_db_status(args: argparse.Namespace, conn) -> None:
    payload = db_status_payload(conn)

    if args.output_json:
        print(json.dumps(payload, indent=2))
        return

    retailers = payload["retailers"]
    if not retailers:
        print("Database is initialized but has no retailer data yet.")
        return

    for row in retailers:
        print(f"{row['retailer']}:")
        print(f"  orders:              {row['orders']}")
        print(f"  transactions:        {row['transactions']}")
        print(f"  first order date:    {row['first_order_date'] or '-'}")
        print(f"  latest order date:   {row['latest_order_date'] or '-'}")
        print(f"  bound account:       {row['bound_account'] or '-'}")
        print(f"  last import:         {row['last_import_finished_at'] or '-'}")
        print(f"  last import status:  {row['last_import_status'] or '-'}")


def _handle_collect(args: argparse.Namespace, conn, retailer_id: str) -> None:
    collector = REGISTRY[retailer_id]

    # Retailer-namespaced defaults for outdir and user-data-dir
    outdir = args.outdir or Path(f"data/raw/{retailer_id}")
    user_data_dir = args.user_data_dir or Path(f"data/raw/{retailer_id}/browser_profile")

    # --saved-run-dir implies --test-run
    test_run = args.test_run or (args.saved_run_dir is not None)
    known_order_ids = recent_retailer_order_ids(conn, retailer_id) if args.stop_on_known else None

    result = collector.collect(
        conn=conn,
        output_dir=outdir,
        start_date=args.start_date,
        end_date=args.end_date,
        order_limit=args.order_limit,
        max_pages=args.max_pages,
        headless=not args.headed,
        user_data_dir=user_data_dir,
        test_run=test_run,
        saved_run_dir=args.saved_run_dir,
        stop_when_before_start_date=args.stop_on_known,
        known_order_ids=known_order_ids,
    )

    bound_account = get_retailer_account(conn, retailer_id)
    record_retailer_import_run(
        conn,
        retailer_id,
        result.status,
        result.notes,
        account_key=bound_account["account_key"] if bound_account else None,
        account_label=bound_account["account_label"] if bound_account else None,
    )

    if args.output_json:
        data = {
            "retailer": retailer_id,
            "status": result.status,
            "notes": result.notes,
            "orders_collected": result.orders_collected,
            "items_collected": result.items_collected,
            "listing_pages_scanned": result.listing_pages_scanned,
            "discovered_orders": result.discovered_orders,
            "known_orders_matched": result.known_orders_matched,
            "reconciliation": {
                "orders": {
                    "inserted": result.orders_inserted,
                    "updated": result.orders_updated,
                    "unchanged": result.orders_unchanged,
                },
                "shipments": {
                    "inserted": result.shipments_inserted,
                    "updated": result.shipments_updated,
                    "unchanged": result.shipments_unchanged,
                },
                "items": {
                    "inserted": result.items_inserted,
                    "updated": result.items_updated,
                    "unchanged": result.items_unchanged,
                    "deleted": result.items_deleted,
                },
                "retailer_transactions": {
                    "inserted": result.amazon_txns_inserted,
                    "updated": result.amazon_txns_updated,
                    "unchanged": result.amazon_txns_unchanged,
                    "deleted": result.amazon_txns_deleted,
                },
                "item_transaction_links_written": result.item_txn_links_written,
            },
        }
        print(json.dumps(data, indent=2))
        return

    print(f"retailer:   {retailer_id}")
    print(f"status:     {result.status}")
    print(result.notes)
    if result.orders_collected or result.items_collected:
        print(f"\ncollected:  {result.orders_collected} orders, {result.items_collected} items")
        print(f"pages:      {result.listing_pages_scanned} listing pages scanned")
        print(f"discovered: {result.discovered_orders} new, {result.known_orders_matched} already known")
        print("\nreconciliation:")
        print(
            f"  orders       inserted={result.orders_inserted}"
            f"  updated={result.orders_updated}"
            f"  unchanged={result.orders_unchanged}"
        )
        print(
            f"  shipments    inserted={result.shipments_inserted}"
            f"  updated={result.shipments_updated}"
            f"  unchanged={result.shipments_unchanged}"
        )
        print(
            f"  items        inserted={result.items_inserted}"
            f"  updated={result.items_updated}"
            f"  unchanged={result.items_unchanged}"
            f"  deleted={result.items_deleted}"
        )
        print(
            f"  txns         inserted={result.amazon_txns_inserted}"
            f"  updated={result.amazon_txns_updated}"
            f"  unchanged={result.amazon_txns_unchanged}"
            f"  deleted={result.amazon_txns_deleted}"
        )
        print(f"  item-txn links written: {result.item_txn_links_written}")


def _handle_login(args: argparse.Namespace, conn) -> None:
    collector = REGISTRY[args.retailer]
    user_data_dir = args.user_data_dir or Path(f"data/raw/{args.retailer}/browser_profile")

    try:
        result = collector.login(
            user_data_dir=user_data_dir,
            check_only=args.check,
            timeout_s=args.timeout,
        )
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.status == "logged_in" and result.account_label:
        try:
            ensure_retailer_account(
                conn,
                args.retailer,
                result.account_label,
                account_key=result.account_key,
                profile_path=str(user_data_dir),
            )
        except RetailerAccountMismatchError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.output_json:
        print(json.dumps({
            "retailer": args.retailer,
            "status": result.status,
            "message": result.message,
            "already_logged_in": result.already_logged_in,
            "account_label": result.account_label,
        }))
    else:
        print(result.message)

    if result.status not in ("logged_in",):
        sys.exit(1)


def _handle_import(args: argparse.Namespace, conn) -> None:
    count = import_transactions_csv(conn, args.csv, args.account_id)

    if args.output_json:
        print(json.dumps({"imported": count, "source": str(args.csv), "account_id": args.account_id}))
        return

    label = f" (account: {args.account_id})" if args.account_id else ""
    print(f"Imported {count} transaction(s) from {args.csv}{label}")


def _handle_export(args: argparse.Namespace, conn) -> None:
    outputs = export_reports(conn, args.outdir)

    if args.output_json:
        print(json.dumps({k: str(v) for k, v in outputs.items()}, indent=2))
        return

    print(f"Reports written to {args.outdir}/")
    for name, path in outputs.items():
        size = path.stat().st_size if path.exists() else 0
        print(f"  {path.name}  ({size} bytes)")


def _actual_config_payload(cfg) -> dict[str, object]:
    return {
        "configured": cfg is not None,
        "base_url": cfg.base_url if cfg else None,
        "file": cfg.file if cfg else None,
        "account_name": cfg.account_name if cfg else None,
        "password_configured": bool(cfg.password) if cfg else False,
    }


def _handle_actual_configure(args: argparse.Namespace, conn) -> None:
    from .actual_sync import ActualConfig, load_config, save_config, test_connection

    existing = load_config(conn)
    if args.show:
        payload = _actual_config_payload(existing)
        if args.output_json:
            print(json.dumps(payload, indent=2))
        elif not payload["configured"]:
            print("Actual Budget is not configured.")
        else:
            print("Actual Budget configuration:")
            print(f"  base_url:            {payload['base_url']}")
            print(f"  file:                {payload['file']}")
            print(f"  account_name:        {payload['account_name'] or '-'}")
            print(f"  password_configured: {'yes' if payload['password_configured'] else 'no'}")
        return

    base_url = args.base_url or (existing.base_url if existing else None)
    file_name = args.file or (existing.file if existing else None)
    password = args.password or (existing.password if existing else None)
    if password is None:
        password = getpass.getpass("Actual Budget password: ").strip()
    account_name = existing.account_name if existing else None
    if args.clear_account_name:
        account_name = None
    elif args.account_name is not None:
        account_name = args.account_name.strip() or None

    if not base_url or not file_name or not password:
        print(
            "Error: Actual Budget configuration requires base_url, file, and password. "
            "Provide them on the first run of actual-configure.",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = ActualConfig(
        base_url=base_url.strip(),
        password=password,
        file=file_name.strip(),
        account_name=account_name,
    )

    if args.test_connection:
        try:
            test_connection(cfg)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    save_config(conn, cfg)
    payload = _actual_config_payload(cfg)

    if args.output_json:
        print(json.dumps({**payload, "connection_tested": args.test_connection}, indent=2))
        return

    print("Actual Budget configuration saved.")
    print(f"  base_url:            {payload['base_url']}")
    print(f"  file:                {payload['file']}")
    print(f"  account_name:        {payload['account_name'] or '-'}")
    print(f"  password_configured: {'yes' if payload['password_configured'] else 'no'}")
    if args.test_connection:
        print("  connection_tested:   yes")


def _handle_audit(args: argparse.Namespace, conn, mode: str) -> None:
    from .audit import audit_amazon

    retailer_id = getattr(args, "retailer", "amazon")
    outdir = Path(f"data/raw/{retailer_id}")
    user_data_dir = args.user_data_dir or Path(f"data/raw/{retailer_id}/browser_profile")

    result = audit_amazon(
        conn=conn,
        mode=mode,
        output_dir=outdir,
        headless=not args.headed,
        user_data_dir=user_data_dir,
    )

    if args.output_json:
        print(json.dumps(result.to_dict(), indent=2))
        if result.status not in ("ok",):
            sys.exit(1)
        return

    mode_label = "Full Audit (from first transaction)" if mode == "full" else "Latest Audit (since last import)"
    print(f"Amazon {mode_label}")
    print(f"  anchor date:    {result.anchor_date or '-'}")
    print(f"  status:         {result.status}")
    if result.status != "ok":
        print(f"  {result.notes}", file=sys.stderr)
        sys.exit(1)

    print(f"  pages scanned:  {result.pages_scanned}")
    print(f"  Amazon orders:  {result.amazon_orders_in_scope}")
    print(f"  local DB orders:{result.db_orders_in_scope}")
    print(f"  missing:        {len(result.missing_orders)}")
    print()

    if result.missing_orders:
        print("Orders on Amazon not in local database:")
        for m in result.missing_orders:
            date_str = m.order_date or "unknown date"
            print(f"  {m.order_id}  {date_str}")
        print()
        if result.missing_orders:
            dates = [m.order_date for m in result.missing_orders if m.order_date]
            if dates:
                min_date = min(dates)
                max_date = max(dates)
                print(
                    f"To import missing orders, run:\n"
                    f"  amazon-spending collect --retailer {retailer_id}"
                    f" --start-date {min_date} --end-date {max_date}"
                )
    else:
        print(result.notes)


def _run_actual_setup_wizard(conn) -> "ActualConfig":
    """Interactive first-time setup wizard for Actual Budget. Returns a saved, tested config."""
    from .actual_sync import ActualConfig, save_config, test_connection

    print("Actual Budget is not configured yet. Let's set it up now.")
    print()

    base_url = input("  Server URL (e.g. http://localhost:5006): ").strip()
    if not base_url:
        print("Error: server URL is required.", file=sys.stderr)
        sys.exit(1)

    file_name = input("  Budget file name: ").strip()
    if not file_name:
        print("Error: budget file name is required.", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("  Password: ").strip()
    if not password:
        print("Error: password is required.", file=sys.stderr)
        sys.exit(1)

    account_name_raw = input("  Account name to restrict matching (leave blank for all accounts): ").strip()
    account_name = account_name_raw or None

    cfg = ActualConfig(
        base_url=base_url,
        password=password,
        file=file_name,
        account_name=account_name,
    )

    print()
    print("Testing connection...", end=" ", flush=True)
    try:
        test_connection(cfg)
    except RuntimeError as exc:
        print("failed.")
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("OK")
    save_config(conn, cfg)
    print("Configuration saved. Proceeding with sync.")
    print()
    return cfg


def _handle_actual_sync(args: argparse.Namespace, conn) -> None:
    from .actual_sync import load_config, sync_to_actual

    cfg = load_config(conn)
    if cfg is None:
        if args.output_json:
            print(
                '{"error": "Actual Budget is not configured. Run: amazon-spending actual-configure --base-url <url> --file <budget>"}',
                file=sys.stderr,
            )
            sys.exit(1)
        cfg = _run_actual_setup_wizard(conn)

    try:
        result = sync_to_actual(conn, cfg, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output_json:
        print(json.dumps({"dry_run": args.dry_run, **result.to_dict()}, indent=2))
        return

    mode = " (dry run)" if args.dry_run else ""
    print(f"Actual Budget sync{mode}: {cfg.base_url} / {cfg.file!r}")
    print(f"  synced:    {result.synced}")
    print(f"  no match:  {result.no_match}")
    if result.errors:
        print(f"  errors:    {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        init_db(conn)

        if args.command == "init-db":
            print(f"Database initialized at {args.db}")
        elif args.command == "db-status":
            _handle_db_status(args, conn)
        elif args.command == "collect":
            _handle_collect(args, conn, args.retailer)
        elif args.command == "collect-amazon":
            # Legacy alias — behaves exactly like collect --retailer amazon
            _handle_collect(args, conn, "amazon")
        elif args.command == "import-transactions":
            _handle_import(args, conn)
        elif args.command == "export":
            _handle_export(args, conn)
        elif args.command == "actual-configure":
            _handle_actual_configure(args, conn)
        elif args.command == "actual-sync":
            _handle_actual_sync(args, conn)
        elif args.command == "login":
            _handle_login(args, conn)
        elif args.command == "audit":
            _handle_audit(args, conn, args.mode)
        elif args.command == "from-first-transaction":
            _handle_audit(args, conn, "full")
        elif args.command == "from-latest-transaction":
            _handle_audit(args, conn, "latest")
        else:
            parser.error(f"Unknown command: {args.command}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
