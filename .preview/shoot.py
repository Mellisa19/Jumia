"""Preview helper: screenshot the app's main pages for a visual UI/UX review."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent.parent / "socratic-preview"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:5057"

PAGES = [
    ("02-monthly-sales", "/"),
    ("03-daily-sales", "/daily_sales"),
    ("04-monthly-repurchases", "/monthly_repurchases"),
    ("05-rankings", "/rankings"),
    ("06-top-cities", "/top_cities"),
    ("07-lapsed-customers", "/lapsed-customers"),
    ("08-first-time-orders", "/first-time-orders"),
    ("09-stats", "/stats"),
    ("10-performance", "/performance"),
    ("11-orders-api", "/options/orders-api"),
    ("12-email-templates", "/email-templates"),
]

with sync_playwright() as p:
    browser = p.chromium.launch()

    # The login screen first, from a session that is not signed in yet.
    anon = browser.new_page(viewport={"width": 1500, "height": 1000})
    anon.goto(f"{BASE}/login", wait_until="networkidle")
    anon.screenshot(path=str(OUT / "01-login.png"), full_page=True)
    print("OK   01-login                   /login")
    anon.close()

    page = browser.new_page(viewport={"width": 1500, "height": 1000})

    # Log in once; the session cookie carries the rest of the captures.
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill("input[name=username]", "demo")
    page.fill("input[name=password]", "demo1234")
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle", timeout=60000)
    print("logged in ->", page.url)

    for name, path in PAGES:
        try:
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(1200)
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target), full_page=True)
            heading = page.query_selector("h1")
            title = heading.inner_text().strip()[:60] if heading else page.title()[:60]
            print(f"OK   {name:26s} {path:24s} {title!r}")
        except Exception as exc:
            print(f"FAIL {name:26s} {path:24s} {type(exc).__name__}: {exc}")

    browser.close()

print("saved to", OUT)
