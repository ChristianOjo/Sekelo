"""
Sekelo — Construction Price Intelligence
Cashbuild Scraper
"""

import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

SUPABASE_URL = "https://glvpdeneagsqwxzrtaln.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdsdnBkZW5lYWdzcXd4enJ0YWxuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzODQ4NDQsImV4cCI6MjA4Nzk2MDg0NH0.y5gJY1XRFj5uGYUjnkZ9rPfLQRdub5uKBn8jIxEpdP8"
HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal"
}

BORDER_PREMIUM = 0.20
ZAR_TO_SZL     = 1.0

BRANCHES = [
    {"name": "Southgate | Cashbuild",      "city": "Joburg",    "search": "Southgate"},
    {"name": "Nelspruit Plaza | Cashbuild", "city": "Nelspruit", "search": "Nelspruit Plaza"},
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

# ── SUPABASE ────────────────────────────────────────────────────

def get_previous_price(material_id, city):
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
        print(f"  X Supabase insert failed: {res.status_code} {res.text}")
        return None

# ── BROWSER ─────────────────────────────────────────────────────

def bake_store_cookie(context, branch_name, first_product_url):
    """Select store once, wait for networkidle, re-navigate to confirm cookie is set."""
    page = context.new_page()
    try:
        page.goto(first_product_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

        modal = page.query_selector("#storeSelectorModal.in")
        if not modal:
            print(f"  [setup] No modal on load — checking store list anyway")

        page.wait_for_selector(".store-list", timeout=8000)
        time.sleep(1)

        stores = page.query_selector_all(".store-list li, .store-list .store-item")
        search_term = branch_name.split("|")[0].strip().lower()
        clicked = False
        for store in stores:
            if search_term in store.inner_text().lower():
                store.click()
                clicked = True
                break

        if not clicked:
            print(f"  [setup] Branch not found: {branch_name}")
            return

        # Wait for page to fully react to store selection
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            time.sleep(5)

        # Re-navigate to confirm cookie is baked
        page.goto(first_product_url, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            time.sleep(4)

        print(f"  [setup] Store cookie baked: {branch_name}")

    except Exception as e:
        print(f"  [setup] Failed: {e}")
    finally:
        page.close()


def store_still_needed(page, branch_name):
    """If modal reappeared, re-select the store."""
    modal = page.query_selector("#storeSelectorModal.in")
    if not modal:
        return
    print(f"  [reselect] Modal reappeared — re-selecting store")
    try:
        page.wait_for_selector(".store-list", timeout=8000)
        stores = page.query_selector_all(".store-list li, .store-list .store-item")
        search_term = branch_name.split("|")[0].strip().lower()
        for store in stores:
            if search_term in store.inner_text().lower():
                store.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    time.sleep(4)
                break
    except Exception as e:
        print(f"  [reselect] Failed: {e}")


def extract_price(page):
    """
    Wait for a price element that contains an actual numeric value (not empty/placeholder).
    Uses wait_for_selector with :has-text to ensure the Rand value has loaded.
    Returns float or None.
    """
    price = None  # FIX 1: always reset before extraction
    try:
        # Wait for price element to contain 'R' (confirms value has loaded, not placeholder)
        page.wait_for_selector("span.current-price-value:has-text('R')", timeout=10000)
        el = page.query_selector("span.current-price-value")
        if el:
            content = el.get_attribute("content")
            if content and content.strip():
                price = float(content)
    except Exception:
        # Fallback: try getting content attribute directly without text check
        try:
            el = page.query_selector("span.current-price-value")
            if el:
                content = el.get_attribute("content")
                if content and content.strip() and content != "0":
                    price = float(content)
        except Exception:
            price = None
    return price

# ── SCRAPE ───────────────────────────────────────────────────────

def scrape():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'─'*55}")
    print(f"  Sekelo Scraper — {timestamp}")
    print(f"{'─'*55}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for branch in BRANCHES:
            print(f"  {branch['name']} ({branch['city']})")

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            # Bake store cookie using first product page
            bake_store_cookie(context, branch["name"], PRODUCTS[0]["url"])

            for product in PRODUCTS:
                price_zar = None  # FIX 1: explicit variable purge each iteration

                page = context.new_page()
                try:
                    print(f"  -> {product['label']}")

                    # Navigate to product
                    page.goto(product["url"], timeout=30000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        time.sleep(4)

                    # FIX 3: check if store modal reappeared and re-select if needed
                    store_still_needed(page, branch["name"])

                    # FIX 2: extract price only after value has loaded
                    price_zar = extract_price(page)

                    if price_zar:
                        prev = get_previous_price(product["id"], branch["city"])
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
                        print(f"     R{price_zar} ZAR / E{price_szl} SZL  delta={delta_24h}%")
                    else:
                        print(f"     No price found — skipping")

                except Exception as e:
                    print(f"     Error: {e}")
                finally:
                    page.close()

                time.sleep(2)

            context.close()
            print()

        browser.close()

    print(f"Scrape complete — data live in Supabase\n")


if __name__ == "__main__":
    scrape()
