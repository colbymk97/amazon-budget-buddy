"""Filesystem locations for the budget tool's persistent data.

By default everything lives under the OS-conventional user data directory:

  macOS:    ~/Library/Application Support/amazon-spending/
  Linux:    ~/.local/share/amazon-spending/   (or $XDG_DATA_HOME/amazon-spending/)
  Windows:  %APPDATA%\\amazon-spending\\

Override with the AMAZON_SPENDING_HOME environment variable to use a custom path
(useful for tests, sandboxed runs, or multi-account separation).

Inside the home directory:
  amazon_spending.sqlite3        - the database
  browser_profiles/<retailer>/   - persistent Playwright Chromium profile
  raw/<retailer>/<timestamp>/    - saved HTML snapshots from each collect run

Exports are NOT placed here — they default to ./exports in the current working
directory because the user invokes them and expects the output near them.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "amazon-spending"
ENV_VAR = "AMAZON_SPENDING_HOME"


def app_data_dir() -> Path:
    """Return the directory where the DB and persistent state live.

    Resolution order:
      1. $AMAZON_SPENDING_HOME if set
      2. platformdirs.user_data_dir(APP_NAME)
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir(APP_NAME, appauthor=False))


def default_db_path() -> Path:
    return app_data_dir() / "amazon_spending.sqlite3"


def default_browser_profile_dir(retailer: str) -> Path:
    return app_data_dir() / "browser_profiles" / retailer


def default_raw_outdir(retailer: str) -> Path:
    return app_data_dir() / "raw" / retailer


def default_exports_dir() -> Path:
    """Exports go to ./exports relative to the caller's cwd."""
    return Path.cwd() / "exports"


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------

_LEGACY_DB_RELATIVE = Path("data") / "amazon_spending.sqlite3"
_LEGACY_BROWSER_PROFILE_RELATIVE = Path("data") / "raw" / "amazon" / "browser_profile"


def _db_is_empty(db_path: Path) -> bool:
    """Return True if the target DB has no orders (treat as not-yet-imported)."""
    if not db_path.exists():
        return True
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
            ).fetchone()
            if row is None:
                return True
            (n,) = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
            return n == 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def maybe_migrate_legacy_data() -> None:
    """One-time copy of legacy ./data/ files into the new app-data home.

    Triggers when the target DB is missing or empty AND the cwd contains a
    legacy SQLite database (i.e., you're standing in the project directory).
    Non-destructive: copies, never moves. Idempotent on repeated calls.
    """
    legacy_db = Path.cwd() / _LEGACY_DB_RELATIVE
    if not legacy_db.exists():
        return

    target_db = default_db_path()
    if not _db_is_empty(target_db):
        return

    home = app_data_dir()
    home.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()
    shutil.copy2(legacy_db, target_db)
    print(
        f"[migrate] Copied legacy database {legacy_db} -> {target_db}",
        file=sys.stderr,
    )

    legacy_profile = Path.cwd() / _LEGACY_BROWSER_PROFILE_RELATIVE
    target_profile = default_browser_profile_dir("amazon")
    if legacy_profile.exists() and not target_profile.exists():
        target_profile.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy_profile, target_profile)
        print(
            f"[migrate] Copied legacy browser profile {legacy_profile} -> {target_profile}",
            file=sys.stderr,
        )
