"""
Sekelo — Construction Price Intelligence
Cashbuild Scraper
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
    """
    Navigate to a product page, select the store in the modal,
    wait for the page to fully react, then re-navigate to confirm
    the store cookie is set in the context.
    """
    page = context.new_page()
    try:
        # Step 1: Load product page — modal will appear
        page.goto(first_product_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)

        # Step 2: Check if store modal is open
        modal = page.query_selector("#storeSelectorModal.in")
        if not modal:
            print(f"  [setup] No modal — store may already be set")
            return

        # Step 3: Find and click the correct branch in the store list
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

        # Step 4: Wait for the page to fully react to the store selection
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            time.sleep(4)

        # Step 5: Re-navigate to the same URL to confirm cookie is baked
        page.goto(first_product_url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=8000)

        print(f"  [setup] Store cookie baked: {branch_name}")

    except Exception as e:
        print(f"  [setup] Failed to bake store cookie: {e}")
    finally:
        page.close()


def get_price(context, product_url):
    """
    Navigate to a product page. Store cookie is already set so
    no modal should appear. Wait for price element and extract it.
    """
    page = context.new_page()
    try:
        page.goto(product_url, timeout=30000, wait_until="domcontentloaded")

        # Wait for network to settle (handles AJAX price updates for variants)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            time.sleep(4)

        # Wait for price element specifically
        try:
            page.wait_for_selector("span.current-price-value", timeout=8000)
        except Exception:
            return None

        el = page.query_selector("span.current-price-value")
        if el:
            content = el.get_attribute("content")
            if content:
                return float(content)
        return None

    except Exception as e:
        print(f"  X Price extraction error: {e}")
        return None
    finally:
        page.close()

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

            # Fresh context per branch
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            # Bake the store cookie once into this context
            bake_store_cookie(context, branch["name"], PRODUCTS[0]["url"])

            # Now fetch each product — store is set, no modal will appear
            for product in PRODUCTS:
                try:
                    print(f"  -> {product['label']}")
                    price_zar = get_price(context, product["url"])

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

                time.sleep(2)

            context.close()
            print()

        browser.close()

    print(f"Scrape complete — data live in Supabase\n")


if __name__ == "__main__":
    scrape()
