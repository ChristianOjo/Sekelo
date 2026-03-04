"""
Sekelo — Cashbuild Scraper
Production v2.0 (NUCLEAR FIX)

All URLs stripped at point of use.
Price ranges tightened to prevent wrong element capture.
Each product gets fresh page state.
"""

import time
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── CONFIG ─────────────────────────────────────────────────────

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

# TIGHTENED PRICE RANGES — Prevents wrong element capture
PRODUCTS = [
    {"id": "cement", "label": "AfriSam All Purpose 42.5N 50kg", "url": "https://www.cashbuild.co.za/cement-yard/301-cement-afrisam-all-purpose-425n", "ajax_wait": 25, "min_price": 100, "max_price": 150, "needs_store_select": True},
    {"id": "rebar", "label": "Steel Rebar Y12", "url": "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa", "ajax_wait": 10, "min_price": 100, "max_price": 200, "needs_store_select": False},
    {"id": "timber", "label": "Structural Timber S5 38x114 6.0m", "url": "https://www.cashbuild.co.za/timber/19160-structural-timber-sabs-untreated-38x114-60m", "ajax_wait": 15, "min_price": 180, "max_price": 300, "needs_store_select": False},
    {"id": "bricks", "label": "Concrete Block MB-140", "url": "https://www.cashbuild.co.za/cement-blocks/1099412-block-concrete-mb-140", "ajax_wait": 25, "min_price": 8, "max_price": 18, "needs_store_select": True},
    {"id": "bricks_maxi", "label": "Cement Brick Solid Maxi", "url": "https://www.cashbuild.co.za/cement-plaster-bricks/1099234-brick-cement-solid-maxi", "ajax_wait": 20, "min_price": 5, "max_price": 15, "needs_store_select": True},
    {"id": "concrete_mix", "label": "Concrete Mix 40kg", "url": "https://www.cashbuild.co.za/premix/325-concrete-mix-40kg-bag", "ajax_wait": 20, "min_price": 35, "max_price": 70, "needs_store_select": True},
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

def push_price(material_id, material, branch, city, price_zar, delta_24h, available=True):
    price_szl = round(price_zar * ZAR_TO_SZL * (1 + BORDER_PREMIUM), 2) if price_zar else None
    payload = {
        "material_id": material_id, "material": material, "branch": branch,
        "city": city, "source": "cashbuild", "price_zar": price_zar, "price_szl": price_szl,
        "delta_24h": delta_24h, "currency": "ZAR", "available": available
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, json=payload)
    return price_szl

# ── BROWSER ─────────────────────────────────────────────────────

def dismiss_modal(page):
    for _ in range(3):
        modal = page.query_selector("#storeSelectorModal")
        if not modal:
            return True
        backdrop = page.query_selector("#storeSelectorModal .modal-backdrop")
        if backdrop:
            try:
                backdrop.click(force=True)
            except:
                pass
        for _ in range(20):
            modal = page.query_selector("#storeSelectorModal")
            if not modal or modal.is_hidden():
                return True
            page.wait_for_timeout(300)
    return False

def select_store(page, search_term):
    try:
        page.wait_for_selector(".store-list .store-item", timeout=10000)
        page.wait_for_timeout(2000)
    except:
        return False
    stores = page.query_selector_all(".store-list .store-item")
    for store in stores:
        try:
            if search_term.lower() in store.inner_text().strip().lower():
                store.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                store.click(force=True)
                page.wait_for_timeout(3000)
                dismiss_modal(page)
                page.wait_for_timeout(3000)
                return True
        except:
            continue
    return False

def bake_store_cookie(page, branch_name, search_term, start_url):
    print(f"  [setup] Baking cookie for: {branch_name}")
    # STRIP URL AT POINT OF USE
    page.goto(start_url.strip(), wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(3000)
    if not page.query_selector("#storeSelectorModal"):
        print("  [setup] Cookie already set")
        return True
    if select_store(page, search_term):
        print(f"  [setup] Cookie baked: {branch_name}")
        return True
    return False

def extract_price(page, product):
    min_price = product["min_price"]
    max_price = product["max_price"]
    ajax_wait = product.get("ajax_wait", 15)

    # First: wait specifically for span.current-price-value with a real content value
    for _ in range(ajax_wait):
        try:
            els = page.query_selector_all("span.current-price-value")
            for el in els:
                if not el.is_visible():
                    continue
                content = el.get_attribute("content")
                if content:
                    try:
                        price = float(content)
                        if min_price <= price <= max_price:
                            print(f"     [debug] {product['id']}: R{price} via content")
                            return price
                    except:
                        pass
        except:
            pass
        page.wait_for_timeout(1000)

    # Fallback: only use .price text if needs_store_select is False
    # (non-store-gated products like rebar/timber have reliable text prices)
    if not product.get("needs_store_select"):
        try:
            els = page.query_selector_all(".price")
            for el in els:
                if not el.is_visible():
                    continue
                text = el.inner_text().strip().replace("R", "").replace(",", "").strip()
                match = re.search(r'[\d.]+', text)
                if match:
                    try:
                        price = float(match.group())
                        if min_price <= price <= max_price:
                            print(f"     [debug] {product['id']}: R{price} via .price text")
                            return price
                    except:
                        pass
        except:
            pass

    print(f"     [debug] {product['id']}: No price in range [{min_price}-{max_price}]")
    return None

# ── SCRAPE ───────────────────────────────────────────────────────

def scrape():
    print(f"\nSEKELO SCRAPER v2.0 — {datetime.now()}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for branch in BRANCHES:
            print(f"--- {branch['name']} ---")
            context = browser.new_context()
            page = context.new_page()
            
            # STRIP URL AT POINT OF USE
            first_url = PRODUCTS[0]["url"].strip()
            if not bake_store_cookie(page, branch["name"], branch["search"], first_url):
                print("  [error] Could not set store. Skipping branch.")
                context.close()
                continue
            
            for product in PRODUCTS:
                print(f"  -> {product['label']}")
                
                # STRIP URL AT POINT OF USE — THIS IS THE KEY FIX
                product_url = product["url"].strip()
                print(f"     [debug] URL length: {len(product_url)}")
                
                page.goto(product_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                
                # Select store if needed
                if product.get("needs_store_select") and page.query_selector("#storeSelectorModal"):
                    print("     [setup] Selecting store...")
                    select_store(page, branch["search"])
                    page.wait_for_timeout(2000)
                
                # Extract price
                price = extract_price(page, product)
                
                if price:
                    prev = get_previous_price(product["id"], branch["city"])
                    delta = round(((price - prev["price_zar"]) / prev["price_zar"]) * 100, 2) if prev and prev.get("price_zar") else None
                    push_price(product["id"], product["label"], branch["name"], branch["city"], price, delta)
                    print(f"     ✅ R{price:.2f}")
                else:
                    push_price(product["id"], product["label"], branch["name"], branch["city"], None, None, available=False)
                    print("     ⚠️  UNAVAILABLE")
                
                time.sleep(1)
            
            context.close()
            print()
        
        browser.close()
    
    print("\n✅ COMPLETE\n")

if __name__ == "__main__":
    scrape()
