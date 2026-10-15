"""Preview helper: capture the app's screens after their data has been generated."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent.parent / "socratic-preview"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:5057"

PAGES = [
    ("03-daily-sales", "/daily_sales?date_range=year_to_date"),
    ("04-monthly-repurchases", "/monthly_repurchases"),
    ("05-rankings", "/rankings"),
    ("06-top-cities", "/top_cities"),
    ("07-lapsed-customers", "/lapsed-customers"),
    ("08-first-time-orders", "/first-time-orders"),
    ("09-stats", "/stats"),
    ("10-performance", "/performance"),
    ("12-email-templates", "/email-templates"),
]

browser = None
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 1000})

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill("input[name=username]", "demo")
    page.fill("input[name=password]", "demo1234")
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("networkidle", timeout=60000)
    print("logged in ->", page.url)

    for name, path in PAGES:
        try:
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            h1 = page.query_selector("h1")
            print(f"OK   {name:24s} {(h1.inner_text().strip()[:46] if h1 else page.title())[:46]!r}")
        except Exception as exc:
            print(f"FAIL {name:24s} {type(exc).__name__}: {str(exc)[:100]}")

    browser.close()
print("done")
