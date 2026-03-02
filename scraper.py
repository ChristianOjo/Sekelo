"""
Sekelo — Construction Price Intelligence
Cashbuild Scraper - Final Production Version
"""

import time
import re
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
    {"id": "cement", "label": "PPC Cement 50kg", "url": "https://www.cashbuild.co.za/cement-yard/300426-cement-afrisam-rapo-525r-50kg", "ajax_wait": 25, "min_price": 80, "max_price": 150, "needs_fresh_store": True},
    {"id": "rebar", "label": "Steel Rebar Y12", "url": "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa", "ajax_wait": 10, "min_price": 100, "max_price": 200, "needs_fresh_store": False},
    {"id": "timber", "label": "Structural Timber S5", "url": "https://www.cashbuild.co.za/timber/18160-structural-timber-sabs-untreated-50x76-60m", "ajax_wait": 15, "min_price": 180, "max_price": 300, "needs_fresh_store": False},
    {"id": "bricks", "label": "Concrete Block 390x190x140", "url": "https://www.cashbuild.co.za/cement-blocks/1009603-block-concrete-390-x190-x140", "ajax_wait": 35, "min_price": 100, "max_price": 200, "needs_fresh_store": True},
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
    """Aggressively dismiss the store selector modal."""
    for attempt in range(3):
        modal = page.query_selector("#storeSelectorModal")
        if not modal:
            return True
        
        backdrop = page.query_selector("#storeSelectorModal .modal-backdrop")
        if backdrop:
            try:
                backdrop.click(force=True)
            except Exception:
                pass
        
        close_btn = page.query_selector("#storeSelectorModal .close, #storeSelectorModal button.close")
        if close_btn:
            try:
                close_btn.click(force=True)
            except Exception:
                pass
        
        for i in range(20):
            modal = page.query_selector("#storeSelectorModal")
            if not modal or modal.is_hidden():
                return True
            page.wait_for_timeout(500)
    
    return False


def select_store(page, search_term):
    """Select store on current page."""
    try:
        page.wait_for_selector(".store-list .store-item", timeout=15000)
        page.wait_for_timeout(3000)
    except Exception:
        print("  [setup] Store list not found")
        return False
    
    stores = page.query_selector_all(".store-list .store-item")
    search_lower = search_term.lower().strip()
    
    for store in stores:
        try:
            store_text = store.inner_text().strip().lower()
            if search_lower in store_text:
                store.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(1000)
                store.wait_for_element_state("stable", timeout=10000)
                store.click(force=True)
                page.wait_for_timeout(5000)
                dismiss_modal(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(5000)
                return True
        except Exception:
            continue
    
    return False


def bake_store_cookie(page, branch_name, search_term, start_url):
    """Select store ONCE per branch for products that support it."""
    print(f"  [setup] Baking cookie for: {branch_name}")
    
    page.goto(start_url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(5000)
    
    modal = page.query_selector("#storeSelectorModal")
    if not modal:
        print("  [setup] No modal, cookie already set")
        return True
    
    if select_store(page, search_term):
        print(f"  [setup] Cookie baked: {branch_name}")
        return True
    
    print(f"  [setup] Branch not found: {search_term}")
    return False


def extract_price_safe(page, product, max_retries=3):
    """Extract price with product-specific handling."""
    
    # Extended selectors for blocks
    if product["id"] == "bricks":
        price_selectors = [
            "span.current-price-value",
            ".product-single__price .money",
            ".product-price .money",
            "span.money",
            "[data-price]",
            ".price",
            ".product-single__price",
            ".product-info .price",
            ".product-pricing .price",
            ".price-wrapper .price",
            "div.price",
            "span.price",
            ".product-single__price",
        ]
    else:
        price_selectors = [
            "span.current-price-value",
            ".product-single__price .money",
            "span.money",
            ".price",
            ".product-price",
        ]
    
    ajax_wait = product.get("ajax_wait", 10)
    min_price = product.get("min_price", 0)
    max_price = product.get("max_price", 9999)
    product_id = product.get("id", "unknown")
    
    for retry in range(max_retries):
        try:
            page.wait_for_timeout(ajax_wait * 1000)
            
            # Debug: check what's on the page
            if retry == 0:
                all_prices = page.query_selector_all(".price, span.money, [data-price]")
                print(f"  [debug] {product_id}: Found {len(all_prices)} price elements on page")
                for i, el in enumerate(all_prices[:5]):
                    try:
                        content = el.get_attribute("content")
                        text = el.inner_text().strip()[:50]
                        print(f"  [debug]   [{i}] content='{content}' text='{text}'")
                    except Exception:
                        pass
            
            for selector in price_selectors:
                try:
                    els = page.query_selector_all(selector)
                    for el in els:
                        if not el.is_visible():
                            continue
                        
                        content_val = el.get_attribute("content")
                        if content_val:
                            try:
                                price = float(content_val)
                                if min_price <= price <= max_price:
                                    print(f"  [extract] {product_id}: R{price} via {selector} (content)")
                                    return price
                            except ValueError:
                                pass
                        
                        text_val = el.inner_text().strip()
                        if text_val:
                            text_val = text_val.replace("R", "").replace(",", "").replace("each", "").strip()
                            match = re.search(r'[\d.]+', text_val)
                            if match:
                                try:
                                    price = float(match.group())
                                    if min_price <= price <= max_price:
                                        print(f"  [extract] {product_id}: R{price} via {selector} (text)")
                                        return price
                                except ValueError:
                                    pass
                except Exception:
                    continue
            
            if retry < max_retries - 1:
                print(f"  [retry] {product_id}: Attempt {retry + 2}/{max_retries}")
                page.wait_for_timeout(5000)
                    
        except Exception as e:
            print(f"  [error] {product_id}: {e}")
            if retry < max_retries - 1:
                page.wait_for_timeout(5000)
    
    print(f"  [debug] {product_id}: All selectors exhausted")
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

            # Initial cookie bake (for rebar/timber)
            if not bake_store_cookie(page, branch["name"], branch["search"], PRODUCTS[0]["url"]):
                print("  [Error] Could not set store. Skipping branch.")
                context.close()
                continue

            for product in PRODUCTS:
                print(f"  -> {product['label']}")
                
                # Navigate to product page
                page.goto(product["url"], wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(5000)
                
                # CRITICAL: Fresh store selection for Cement/Blocks
                if product.get("needs_fresh_store", False):
                    print("  [setup] Fresh store selection required for this product...")
                    modal = page.query_selector("#storeSelectorModal")
                    if modal:
                        select_store(page, branch["search"])
                    else:
                        # Force modal to appear by clicking a store-related element
                        print("  [setup] No modal, triggering store selection...")
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3000)
                        if page.query_selector("#storeSelectorModal"):
                            select_store(page, branch["search"])
                
                # Dismiss any remaining modal
                if page.query_selector("#storeSelectorModal"):
                    print("  [warn] Modal still present, dismissing...")
                    dismiss_modal(page)
                    page.wait_for_timeout(3000)

                price_zar = extract_price_safe(page, product)

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
