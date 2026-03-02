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
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

BORDER_PREMIUM = 0.20
ZAR_TO_SZL = 1.0

BRANCHES = [
    {"name": "Southgate | Cashbuild", "city": "Joburg", "search": "southgate"},
    {"name": "Nelspruit Plaza | Cashbuild", "city": "Nelspruit", "search": "nelspruit plaza"},
]

PRODUCTS = [
    {"id": "cement", "label": "PPC Cement 50kg", "url": "https://www.cashbuild.co.za/cement-yard/300426-cement-afrisam-rapo-525r-50kg"},
    {"id": "rebar", "label": "Steel Rebar Y12", "url": "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa"},
    {"id": "timber", "label": "Structural Timber S5", "url": "https://www.cashbuild.co.za/timber/18160-structural-timber-sabs-untreated-50x76-60m"},
    {"id": "bricks", "label": "Concrete Block 390x190x140", "url": "https://www.cashbuild.co.za/cement-blocks/1009603-block-concrete-390-x190-x140"},
]

# ── SUPABASE ────────────────────────────────────────────────────

def get_previous_price(material_id, city):
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, params={
            "material_id": f"eq.{material_id}",
            "city": f"eq.{city}",
            "order": "timestamp.desc",
            "limit": "1",
            "select": "price_zar"
        })
        data = res.json()
        return data[0] if data else None
    except Exception:
        return None


def push_price(material_id, material, branch, city, price_zar, delta_24h):
    price_szl = round(price_zar * ZAR_TO_SZL * (1 + BORDER_PREMIUM), 2)
    payload = {
        "material_id": material_id, "material": material, "branch": branch,
        "city": city, "price_zar": price_zar, "price_szl": price_szl,
        "delta_24h": delta_24h, "currency": "ZAR"
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, json=payload)
    return price_szl

# ── BROWSER ─────────────────────────────────────────────────────

def bake_store_cookie(page, branch_name, search_term, start_url):
    """Sets the store context and waits for the redirect to finish."""
    print(f"  [setup] Baking cookie for: {branch_name}")
    
    # Navigate to trigger the store selector modal
    page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)  # Let page settle
    
    # Wait for modal to appear
    try:
        page.wait_for_selector("#storeSelectorModal", timeout=15000)
        print("  [setup] Store modal detected")
    except Exception:
        print("  [setup] No modal found, may already have cookie")
        return True
    
    # Wait for store list to populate
    try:
        page.wait_for_selector(".store-list .store-item", timeout=15000)
        page.wait_for_timeout(2000)  # Extra wait for dynamic content
    except Exception:
        print("  [setup] Store list not found")
        return False
    
    # Get all store elements
    stores = page.query_selector_all(".store-list .store-item")
    print(f"  [setup] Found {len(stores)} stores")
    
    if not stores:
        print("  [setup] No stores found")
        return False
    
    # Search for matching store
    search_lower = search_term.lower().strip()
    for i, store in enumerate(stores):
        try:
            store_text = store.inner_text().strip().lower()
            if search_lower in store_text:
                print(f"  [setup] Match found at index {i}")
                
                # Scroll element into view
                store.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(500)
                
                # Wait for element to be clickable, then click
                store.wait_for_element_state("clickable", timeout=10000)
                store.click(force=True)
                print("  [setup] Store clicked")
                
                # Wait for modal to close (increased timeout + polling)
                print("  [setup] Waiting for modal to close...")
                for attempt in range(30):  # 30 seconds total
                    modal = page.query_selector("#storeSelectorModal")
                    if modal is None:
                        print("  [setup] Modal closed successfully")
                        break
                    # Check if modal has 'fade' class (closing animation)
                    modal_class = modal.get_attribute("class") or ""
                    if "fade" in modal_class and "in" not in modal_class:
                        print("  [setup] Modal is fading out")
                        break
                    page.wait_for_timeout(1000)
                else:
                    print("  [setup] Warning: Modal may still be open, continuing anyway")
                
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(3000)  # Let cookie settle
                print(f"  [setup] Cookie baked: {branch_name}")
                return True
                
        except Exception as e:
            print(f"  [setup] Error with store {i}: {e}")
            continue
    
    print(f"  [setup] Branch not found: {search_term}")
    return False


def extract_price_safe(page, expected_url):
    """Three-point check: correct URL, non-zero content, return float."""
    try:
        page.wait_for_url(expected_url, timeout=10000)
        page.wait_for_timeout(2000)  # Let AJAX fire
        
        # Wait for price to be non-zero (AJAX load)
        try:
            page.wait_for_selector(
                "span.current-price-value[content]:not([content='0'])",
                timeout=15000
            )
        except Exception:
            print("  [extract] Price content attribute not ready, trying text fallback")
        
        el = page.query_selector("span.current-price-value")
        if el:
            # Try content attribute first
            val = el.get_attribute("content")
            if val:
                try:
                    price = float(val)
                    if price > 0:
                        return price
                except ValueError:
                    pass
            
            # Fallback: try to get text content
            text = el.inner_text().strip()
            if text:
                # Remove R symbol and commas
                text = text.replace("R", "").replace(",", "").strip()
                try:
                    price = float(text)
                    if price > 0:
                        return price
                except ValueError:
                    pass
        
        print("  [extract] No valid price found")
                    
    except Exception as e:
        print(f"  [extract] Error: {e}")
        pass
    return None

# ── SCRAPE ───────────────────────────────────────────────────────

def scrape():
    print(f"\nSekelo Scraper Start: {datetime.now()}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for branch in BRANCHES:
            print(f"--- {branch['name']} ---")
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            if not bake_store_cookie(page, branch["name"], branch["search"], PRODUCTS[0]["url"]):
                print("  [Error] Could not set store. Skipping branch.")
                context.close()
                continue

            for product in PRODUCTS:
                print(f"  -> {product['label']}")
                page.goto(product["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)  # Wait for AJAX

                # Re-select store if modal reappeared
                if page.query_selector("#storeSelectorModal"):
                    print("  [warn] Modal reappeared, re-baking cookie")
                    bake_store_cookie(page, branch["name"], branch["search"], product["url"])

                price_zar = extract_price_safe(page, product["url"])

                if price_zar:
                    prev = get_previous_price(product["id"], branch["city"])
                    delta = None
                    if prev and prev.get("price_zar"):
                        delta = round(
                            ((price_zar - prev["price_zar"]) / prev["price_zar"]) * 100, 2
                        )

                    price_szl = push_price(
                        product["id"], product["label"],
                        branch["name"], branch["city"],
                        price_zar, delta
                    )
                    print(f"     SUCCESS: R{price_zar} (E{price_szl}) | Delta: {delta}%")
                else:
                    print("     FAILED: No price found.")

                time.sleep(2)

            context.close()
            print()

        browser.close()

    print("Scrape complete.")


if __name__ == "__main__":
    scrape()
