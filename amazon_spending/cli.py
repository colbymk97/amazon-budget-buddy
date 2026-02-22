from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .collector import collect_amazon
from .db import DEFAULT_DB_PATH, connect, init_db
from .importers import import_transactions_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amazon-spending")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialize SQLite schema")

    p_import = sub.add_parser("import-transactions", help="Import transactions CSV")
    p_import.add_argument("--csv", type=Path, required=True, help="Path to transactions CSV")
    p_import.add_argument("--account-id", type=str, default=None, help="Optional account identifier")

    p_collect = sub.add_parser("collect-amazon", help="Collect Amazon orders into local DB")
    p_collect.add_argument("--outdir", type=Path, default=Path("data/raw/amazon"), help="Raw output directory")
    p_collect.add_argument("--start-date", type=str, default=None, help="YYYY-MM-DD")
    p_collect.add_argument("--end-date", type=str, default=None, help="YYYY-MM-DD")
    p_collect.add_argument("--order-limit", type=int, default=None, help="Max orders to collect")
    p_collect.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max order history pages to traverse (optional; defaults from --order-limit when provided)",
    )
    p_collect.add_argument(
        "--test-run",
        action="store_true",
        help="Parse previously saved raw HTML into DB without launching browser scraping",
    )
    p_collect.add_argument(
        "--saved-run-dir",
        type=Path,
        default=None,
        help="Optional saved raw run dir (defaults to latest under --outdir)",
    )
    p_collect.add_argument(
        "--headed",
        action="store_true",
        help="Force headed browser mode (default is headless with automatic auth fallback)",
    )
    p_collect.add_argument(
        "--user-data-dir",
        type=Path,
        default=Path("data/raw/amazon/browser_profile"),
        help="Persistent browser profile path for session cookies",
    )
    p_view = sub.add_parser("view", help="Open local web viewer")
    p_view.add_argument("--host", type=str, default="127.0.0.1", help="Viewer host")
    p_view.add_argument("--port", type=int, default=8501, help="Viewer port")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        init_db(conn)

        if args.command == "init-db":
            print(f"Initialized database at {args.db}")
        elif args.command == "import-transactions":
            count = import_transactions_csv(conn, args.csv, args.account_id)
            print(f"Imported {count} transactions from {args.csv}")
        elif args.command == "collect-amazon":
            result = collect_amazon(
                conn=conn,
                output_dir=args.outdir,
                start_date=args.start_date,
                end_date=args.end_date,
                order_limit=args.order_limit,
                max_pages=args.max_pages,
                headless=not args.headed,
                user_data_dir=args.user_data_dir,
                test_run=args.test_run,
                saved_run_dir=args.saved_run_dir,
            )
            print(f"status={result.status}")
            print(result.notes)
            if result.orders_collected or result.items_collected:
                print(f"orders_collected={result.orders_collected}")
                print(f"items_collected={result.items_collected}")
                print(
                    "orders_reconciled="
                    f"inserted:{result.orders_inserted},"
                    f"updated:{result.orders_updated},"
                    f"unchanged:{result.orders_unchanged}"
                )
                print(
                    "shipments_reconciled="
                    f"inserted:{result.shipments_inserted},"
                    f"updated:{result.shipments_updated},"
                    f"unchanged:{result.shipments_unchanged}"
                )
                print(
                    "items_reconciled="
                    f"inserted:{result.items_inserted},"
                    f"updated:{result.items_updated},"
                    f"unchanged:{result.items_unchanged},"
                    f"deleted:{result.items_deleted}"
                )
                print(
                    "amazon_transactions_reconciled="
                    f"inserted:{result.amazon_txns_inserted},"
                    f"updated:{result.amazon_txns_updated},"
                    f"unchanged:{result.amazon_txns_unchanged},"
                    f"deleted:{result.amazon_txns_deleted}"
                )
                print(f"item_transaction_links_written={result.item_txn_links_written}")
        elif args.command == "view":
            try:
                import streamlit  # noqa: F401
            except ImportError:
                print("Streamlit is not installed in this environment.")
                print("Run: pip install streamlit")
                return
            app_path = Path(__file__).parent / "webapp.py"
            cmd = [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app_path),
                "--server.address",
                args.host,
                "--server.port",
                str(args.port),
                "--",
                "--db",
                str(args.db),
            ]
            print(f"Starting viewer at http://{args.host}:{args.port}")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as exc:
                print(f"Viewer failed to start (exit={exc.returncode}).")
                raise
        else:
            parser.error("Unknown command")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
