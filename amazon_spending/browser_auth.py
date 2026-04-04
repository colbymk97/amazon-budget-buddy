"""Playwright-based browser login for Amazon.

Uses a persistent Chromium profile so Amazon remembers the device.  On
each call the profile is first checked headlessly — if the ``x-main``
auth cookie is already present the cookies are exported immediately
without opening a visible browser.  Only when authentication is actually
needed is a headed window opened for the user to complete login.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# The amazon-orders library checks for this cookie to determine auth status.
_AUTH_COOKIE = "x-main"

_AMAZON_HOME = "https://www.amazon.com"

_SIGN_IN_URL = (
    "https://www.amazon.com/ap/signin"
    "?openid.pape.max_auth_age=0"
    "&openid.return_to=https%3A%2F%2Fwww.amazon.com%2F%3Fref_%3Dnav_signin"
    "&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
    "&openid.assoc_handle=usflex"
    "&openid.mode=checkid_setup"
    "&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
    "&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
)


@dataclass
class BrowserLoginResult:
    status: str  # "ok" | "error" | "timeout" | "cancelled"
    message: str = ""
    cookies_saved: int = 0


def _playwright_cookies_to_jar(cookies: list[dict]) -> dict[str, str]:
    """Convert Playwright cookie list to the flat {name: value} dict
    that amazon-orders expects in its cookie jar JSON file."""
    return {
        c["name"]: c["value"]
        for c in cookies
        if ".amazon.com" in c.get("domain", "")
    }


def _save_jar(cookie_jar_path: str, cookies: list[dict]) -> int:
    """Extract Amazon cookies and write the JSON jar. Returns cookie count."""
    jar = _playwright_cookies_to_jar(cookies)
    with open(cookie_jar_path, "w", encoding="utf-8") as f:
        json.dump(jar, f, indent=2)
    return len(jar)


def _has_auth_cookie(cookies: list[dict]) -> bool:
    return any(c["name"] == _AUTH_COOKIE for c in cookies)


def browser_login_amazon(
    cookie_jar_path: str,
    profile_dir: str,
    timeout_seconds: int = 300,
    on_status: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> BrowserLoginResult:
    """Refresh the cookie jar from a persistent Chromium profile.

    1. Launch headless with the persistent profile and check for existing
       auth cookies.  If found, export them immediately (no window shown).
    2. If not authenticated, re-launch headed so the user can log in
       manually (CAPTCHAs, 2FA, etc.).  Polls for the auth cookie until
       detected or timeout.

    Parameters
    ----------
    cookie_jar_path:
        Where to write the JSON cookie jar (amazon-orders format).
    profile_dir:
        Persistent Chromium profile directory.
    timeout_seconds:
        Max seconds to wait for the user to complete login (headed phase).
    on_status:
        Optional callback invoked with status messages.
    cancel_event:
        Optional threading.Event; when set the browser closes early.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return BrowserLoginResult(
            status="error",
            message=(
                "Playwright is not installed. Run: "
                "pip install playwright && playwright install chromium"
            ),
        )

    def _status(msg: str) -> None:
        logger.info(msg)
        if on_status:
            on_status(msg)

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    Path(cookie_jar_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Phase 1: headless check — see if profile already has valid cookies
    # ------------------------------------------------------------------
    _status("Checking existing session...")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_AMAZON_HOME, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            cookies = context.cookies()
            if _has_auth_cookie(cookies):
                n = _save_jar(cookie_jar_path, cookies)
                context.close()
                _status("Existing session is valid — cookies refreshed.")
                return BrowserLoginResult(
                    status="ok",
                    message="Existing browser session is still valid. Cookies refreshed.",
                    cookies_saved=n,
                )
            context.close()
    except Exception as exc:
        logger.warning("Headless cookie check failed: %s", exc)
        # Fall through to headed phase.

    # ------------------------------------------------------------------
    # Phase 2: headed browser — user authenticates manually
    # ------------------------------------------------------------------
    _status("Launching browser — please log in to Amazon...")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_SIGN_IN_URL, wait_until="domcontentloaded")

            elapsed = 0.0
            poll_interval = 2.0
            while elapsed < timeout_seconds:
                if cancel_event and cancel_event.is_set():
                    context.close()
                    return BrowserLoginResult(
                        status="cancelled",
                        message="Browser login cancelled by user.",
                    )

                cookies = context.cookies()
                if _has_auth_cookie(cookies):
                    n = _save_jar(cookie_jar_path, cookies)
                    _status("Authentication detected — cookies saved.")
                    context.close()
                    return BrowserLoginResult(
                        status="ok",
                        message="Browser authentication successful.",
                        cookies_saved=n,
                    )

                page.wait_for_timeout(int(poll_interval * 1000))
                elapsed += poll_interval

            context.close()
            return BrowserLoginResult(
                status="timeout",
                message=f"Login was not completed within {timeout_seconds} seconds.",
            )

    except Exception as exc:
        return BrowserLoginResult(status="error", message=str(exc))
