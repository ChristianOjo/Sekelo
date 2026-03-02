"""
Sekelo — Construction Price Intelligence
Cashbuild Scraper

Pulls Big 5 material prices from:
  - Southgate | Cashbuild (Joburg)
  - Nelspruit Plaza | Cashbuild (Nelspruit)

Pushes results directly to Supabase.
Run manually or via Railway cron every 24 hours.
"""

import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── SUPABASE CONFIG ─────────────────────────────────────────────
SUPABASE_URL = "https://glvpdeneagsqwxzrtaln.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdsdnBkZW5lYWdzcXd4enJ0YWxuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzODQ4NDQsImV4cCI6MjA4Nzk2MDg0NH0.y5gJY1XRFj5uGYUjnkZ9rPfLQRdub5uKBn8jIxEpdP8"
HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal"
}

# ── SCRAPER CONFIG ──────────────────────────────────────────────
BORDER_PREMIUM = 0.20  # 20% SZ landed cost over SA shelf price
ZAR_TO_SZL     = 1.0   # Pegged 1:1

BRANCHES = [
    {"name": "Southgate | Cashbuild",      "city": "Joburg",    "search": "Southgate"},
    {"name": "Nelspruit Plaza | Cashbuild", "city": "Nelspruit", "search": "Nelspruit"},
]

PRODUCTS = [
    {
        "id":    "cement",
        "label": "PPC Cement 50kg",
        "url":   "https://www.cashbuild.co.za/cement-yard/300426-cement-afrisam-rapo-525r-50kg",
    },
    {
        "id":    "rebar",
        "label": "Steel Rebar Y12",
        "url":   "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa",
    },
    {
        "id":    "timber",
        "label": "Structural Timber S5",
        "url":   "https://www.cashbuild.co.za/timber/18160-structural-timber-sabs-untreated-50x76-60m",
    },
    {
        "id":    "bricks",
        "label": "Concrete Block 390x190x140",
        "url":   "https://www.cashbuild.co.za/cement-blocks/1009603-block-concrete-390-x190-x140",
    },
]

# ── SUPABASE HELPERS ────────────────────────────────────────────

def get_previous_price(material_id, city):
    """Fetch the most recent price for delta calculation."""
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/prices",
        headers=HEADERS,
        params={
            "material_id": f"eq.{material_id}",
            "city":        f"eq.{city}",
            "order":       "timestamp.desc",
            "limit":       "1",
            "select":      "price_zar,timestamp"
        }
    )
    data = res.json()
    return data[0] if data else None


def push_price(material_id, material, branch, city, price_zar, delta_24h):
    """Insert a new price row into Supabase."""
    price_szl = round(price_zar * ZAR_TO_SZL * (1 + BORDER_PREMIUM), 2)
    payload = {
        "material_id": material_id,
        "material":    material,
        "branch":      branch,
        "city":        city,
        "price_zar":   price_zar,
        "price_szl":   price_szl,
        "delta_24h":   delta_24h,
        "currency":    "ZAR"
    }
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/prices",
        headers=HEADERS,
        json=payload
    )
    if res.status_code in (200, 201):
        return price_szl
    else:
        print(f"  ✗ Supabase insert failed: {res.status_code} {res.text}")
        return None

# ── BROWSER HELPERS ─────────────────────────────────────────────

def dismiss_modal(page):
    """Force-close any open store selector modal via JavaScript."""
    try:
        page.evaluate("""
            var modal = document.getElementById('storeSelectorModal');
            if (modal) {
                modal.classList.remove('in', 'show');
                modal.style.display = 'none';
            }
            var backdrops = document.querySelectorAll('.modal-backdrop');
            backdrops.forEach(function(b) { b.remove(); });
            document.body.classList.remove('modal-open');
        """)
        time.sleep(1)
    except Exception as e:
        print(f"  ⚠ Modal dismiss failed: {e}")


def extract_price(page):
    """Extract price from the current product page."""
    try:
        el = page.query_selector("span.current-price-value")
        if el:
            content = el.get_attribute("content")
            if content:
                return float(content)
        return None
    except Exception as e:
        print(f"  ⚠ Price extraction failed: {e}")
        return None

# ── MAIN SCRAPE ─────────────────────────────────────────────────

def scrape():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'─'*55}")
    print(f"  Sekelo Scraper — {timestamp}")
    print(f"{'─'*55}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        for branch in BRANCHES:
            print(f"📍 {branch['name']} ({branch['city']})")

            for product in PRODUCTS:
                page = context.new_page()
                try:
                    print(f"  → {product['label']}")
                    page.goto(product["url"], timeout=30000, wait_until="domcontentloaded")
                    time.sleep(3)

                    # Dismiss modal before extracting price
                    dismiss_modal(page)

                    price_zar = extract_price(page)

                    if price_zar:
                        prev      = get_previous_price(product["id"], branch["city"])
                        delta_24h = None
                        if prev and prev.get("price_zar"):
                            delta_24h = round(
                                ((price_zar - prev["price_zar"]) / prev["price_zar"]) * 100, 2
                            )

                        price_szl = push_price(
                            product["id"],
                            product["label"],
                            branch["name"],
                            branch["city"],
                            price_zar,
                            delta_24h
                        )

                        print(f"     ✓ R{price_zar} ZAR / E{price_szl} SZL  Δ={delta_24h}%")
                    else:
                        print(f"     ✗ No price found — skipping")

                except Exception as e:
                    print(f"     ✗ Error: {e}")
                finally:
                    page.close()

                time.sleep(2)

            print()

        context.close()
        browser.close()

    print(f"✓ Scrape complete — data live in Supabase\n")


if __name__ == "__main__":
    scrape()
