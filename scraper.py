"""
Sekelo — Construction Price Intelligence
Cashbuild Scraper - Production Version
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
    {"id": "cement", "label": "PPC Cement 50kg", "url": "https://www.cashbuild.co.za/cement-yard/300426-cement-afrisam-rapo-525r-50kg", "ajax_wait": 20, "min_price": 80, "max_price": 150},
    {"id": "rebar", "label": "Steel Rebar Y12", "url": "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa", "ajax_wait": 5, "min_price": 100, "max_price": 200},
    {"id": "timber", "label": "Structural Timber S5", "url": "https://www.cashbuild.co.za/timber/18160-structural-timber-sabs-untreated-50x76-60m", "ajax_wait": 15, "min_price": 150, "max_price": 300},
    {"id": "bricks", "label": "Concrete Block 390x190x140", "url": "https://www.cashbuild.co.za/cement-blocks/1009603-block-concrete-390-x190-x140", "ajax_wait": 25, "min_price": 80, "max_price": 200},
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

def dismiss_modal(page):
    """Force dismiss the store selector modal if present."""
    modal = page.query_selector("#storeSelectorModal")
    if modal:
        backdrop = page.query_selector("#storeSelectorModal .modal-backdrop")
        if backdrop:
            backdrop.click(force=True)
            page.wait_for_timeout(2000)
        
        for attempt in range(20):
            modal = page.query_selector("#storeSelectorModal")
            if modal is None:
                return True
            if modal.is_hidden():
                return True
            page.wait_for_timeout(500)
        return False
    return True


def bake_store_cookie(page, branch_name, search_term, start_url):
    """Sets the store context and waits for the redirect to finish."""
    print(f"  [setup] Baking cookie for: {branch_name}")
    
    page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    
    try:
        page.wait_for_selector("#storeSelectorModal", timeout=15000)
    except Exception:
        page.reload(wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        dismiss_modal(page)
        print(f"  [setup] Cookie baked: {branch_name}")
        return True
    
    try:
        page.wait_for_selector(".store-list .store-item", timeout=15000)
        page.wait_for_timeout(2000)
    except Exception:
        print("  [setup] Store list not found")
        return False
    
    stores = page.query_selector_all(".store-list .store-item")
    
    search_lower = search_term.lower().strip()
    for i, store in enumerate(stores):
        try:
            store_text = store.inner_text().strip().lower()
            if search_lower in store_text:
                store.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(500)
                store.wait_for_element_state("stable", timeout=10000)
                store.click(force=True)
                page.wait_for_timeout(3000)
                dismiss_modal(page)
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(2000)
                page.reload(wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(5000)
                dismiss_modal(page)
                print(f"  [setup] Cookie baked: {branch_name}")
                return True
        except Exception:
            continue
    
    print(f"  [setup] Branch not found: {search_term}")
    return False


def extract_price_safe(page, expected_url, product, max_retries=3):
    """Extract price with validation against expected price range."""
    
    # Prioritized selectors - most accurate first
    price_selectors = [
        "span.current-price-value",      # Primary - has content attribute
        ".product-single__price",
        "span.money",
        "[data-testid='product-price']",
        ".product-price .price",
        ".price-display",
        "span.price",
    ]
    
    ajax_wait = product.get("ajax_wait", 10)
    min_price = product.get("min_price", 0)
    max_price = product.get("max_price", 9999)
    
    for retry in range(max_retries):
        try:
            page.wait_for_url(expected_url, timeout=10000)
            page.wait_for_timeout(ajax_wait * 1000)
            
            for selector in price_selectors:
                try:
                    el = page.query_selector(selector)
                    if el and el.is_visible():
                        # Try content attribute first (most reliable)
                        content_val = el.get_attribute("content")
                        if content_val:
                            try:
                                price = float(content_val)
                                if min_price <= price <= max_price:
                                    print(f"  [extract] Price: R{price} via {selector}")
                                    return price
                            except ValueError:
                                pass
                        
                        # Fallback to text content
                        text_val = el.inner_text().strip()
                        if text_val:
                            text_val = text_val.replace("R", "").replace(",", "").strip()
                            try:
                                price = float(text_val)
                                if min_price <= price <= max_price:
                                    print(f"  [extract] Price: R{price} via {selector}")
                                    return price
                            except ValueError:
                                pass
                except Exception:
                    continue
            
            if retry < max_retries - 1:
                page.wait_for_timeout(3000)
                    
        except Exception:
            if retry < max_retries - 1:
                page.wait_for_timeout(3000)
    
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
                
                if page.query_selector("#storeSelectorModal"):
                    bake_store_cookie(page, branch["name"], branch["search"], product["url"])

                price_zar = extract_price_safe(page, product["url"], product)

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
                    print(f"     ✅ SUCCESS: R{price_zar} (E{price_szl}) | Delta: {delta}%")
                else:
                    print("     ❌ FAILED: No price found.")

                time.sleep(2)

            context.close()
            print()

        browser.close()

    print("Scrape complete.")


if __name__ == "__main__":
    scrape()
