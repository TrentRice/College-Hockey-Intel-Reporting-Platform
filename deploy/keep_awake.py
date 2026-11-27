"""
Visit the public site in a real browser, so Streamlit Community Cloud counts it as in use
and doesn't put it to sleep (free apps sleep after 12 hours without a visitor; docs/cloud.md).

  uv run --with playwright python deploy/keep_awake.py [URL]

Run by GitHub Actions: 5 minutes after the nightly refresh saves new data (CHIRP-data's
workflow), and twice more a day (.github/workflows/keep-awake.yml). A plain HTTP request
doesn't count as a visit: Streamlit only sees the page once it loads and connects, so this
drives a headless browser.

If the app is asleep it clicks the wake-up button. Either way it waits until the dashboard
itself has loaded. Exit code 1 if it doesn't load within 5 minutes.

BROWSER_CHANNEL=chrome uses an installed Google Chrome instead of Playwright's own Chromium
(handy for a local test).
"""

from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = "https://chirp-hockey.streamlit.app"
WAKE_BUTTON = re.compile(r"get this app back up", re.I)
LOADED_TEXT = "Win probability"  # a dashboard tab: only there once the app itself has loaded
WAIT_SECONDS = 300


def dashboard_loaded(page) -> bool:
    for frame in page.frames:  # Streamlit Cloud shows the app inside a frame
        try:
            if frame.get_by_text(LOADED_TEXT, exact=True).count():
                return True
        except Exception:  # a frame can detach while the app (re)starts
            continue
    return False


def visit(url: str) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.get_by_role("button", name=WAKE_BUTTON).click(timeout=15_000)
            print("The app was asleep: clicked the wake-up button.")
        except PlaywrightTimeout:
            print("The app was awake.")
        started = time.monotonic()
        while time.monotonic() - started < WAIT_SECONDS:
            if dashboard_loaded(page):
                page.wait_for_timeout(20_000)  # stay a moment, like a person would
                print(f"Dashboard loaded after {time.monotonic() - started:.0f}s.")
                browser.close()
                return 0
            page.wait_for_timeout(5_000)
        browser.close()
    print(f"The dashboard didn't load within {WAIT_SECONDS // 60} minutes.")
    return 1


if __name__ == "__main__":
    sys.exit(visit(sys.argv[1] if len(sys.argv) > 1 else URL))
