"""
Sekelo — Cashbuild Scraper
Production v1.0
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
    "Prefer": "return-minimal"
}

BORDER_PREMIUM = 0.20
ZAR_TO_SZL = 1.0

CASHBUILD_BRANCHES = [
    {"name": "Southgate | Cashbuild", "city": "Joburg", "search": "southgate"},
    {"name": "Nelspruit Plaza | Cashbuild", "city": "Nelspruit", "search": "nelspruit plaza"},
]

CASHBUILD_PRODUCTS = [
    {"id": "bricks_cashbuild", "label": "Cement Brick Solid Maxi", "url": "https://www.cashbuild.co.za/cement-plaster-bricks/1099234-brick-cement-solid-maxi", "ajax_wait": 20, "min_price": 8, "max_price": 20, "needs_store_select": True},
    {"id": "sandpak", "label": "Concrete Mix 40kg", "url": "https://www.cashbuild.co.za/premix/325-concrete-mix-40kg-bag", "ajax_wait": 20, "min_price": 30, "max_price": 80, "needs_store_select": True},
]

# ── SUPABASE ────────────────────────────────────────────────────

def get_previous_price(material_id, city):
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, params={
            "material_id": f"eq.{material_id}",
            "city": f"eq.{city}",
            "source": f"eq.cashbuild",
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
        "material_id": material_id,
        "material": material,
        "branch": branch,
        "city": city,
        "source": "cashbuild",
        "price_zar": price_zar,
        "price_szl": price_szl,
        "delta_24h": delta_24h,
        "currency": "ZAR",
        "available": available
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, json=payload)
    return price_szl

# ── BROWSER ─────────────────────────────────────────────────────

def dismiss_modal(page):
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
        for i in range(20):
            modal = page.query_selector("#storeSelectorModal")
            if not modal or modal.is_hidden():
                return True
            page.wait_for_timeout(300)
    return False


def select_store(page, search_term):
    try:
        page.wait_for_selector(".store-list .store-item", timeout=10000)
        page.wait_for_timeout(2000)
    except Exception:
        return False
    stores = page.query_selector_all(".store-list .store-item")
    search_lower = search_term.lower().strip()
    for store in stores:
        try:
            store_text = store.inner_text().strip().lower()
            if search_lower in store_text:
                store.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                store.wait_for_element_state("stable", timeout=8000)
                store.click(force=True)
                page.wait_for_timeout(3000)
                dismiss_modal(page)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)
                return True
        except Exception:
            continue
    return False


def bake_store_cookie(page, branch_name, search_term, start_url):
    print(f"  [setup] Baking cookie for: {branch_name}")
    page.goto(start_url.strip(), wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(3000)
    modal = page.query_selector("#storeSelectorModal")
    if not modal:
        print("  [setup] No modal, cookie already set")
        return True
    if select_store(page, search_term):
        print(f"  [setup] Cookie baked: {branch_name}")
        return True
    return False


def extract_price(page, product, max_retries=2):
    price_selectors = ["span.current-price-value", ".price", ".product-single__price .money", "span.money"]
    ajax_wait = product.get("ajax_wait", 10)
    min_price = product.get("min_price", 0)
    max_price = product.get("max_price", 9999)
    product_id = product.get("id", "unknown")
    
    for retry in range(max_retries):
        try:
            page.wait_for_timeout(ajax_wait * 1000)
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
                                    print(f"  [extract] {product_id}: R{price:.2f}")
                                    return price
                            except ValueError:
                                pass
                        text_val = el.inner_text().strip()
                        if text_val:
                            text_val = text_val.replace("R", "").replace(",", "").strip()
                            match = re.search(r'[\d.]+', text_val)
                            if match:
                                try:
                                    price = float(match.group())
                                    if min_price <= price <= max_price:
                                        print(f"  [extract] {product_id}: R{price:.2f}")
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
    print(f"\n{'='*60}")
    print(f"SEKELO — CASHBUILD SCRAPER")
    print(f"Start: {datetime.now()}")
    print(f"{'='*60}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for branch in CASHBUILD_BRANCHES:
            print(f"--- {branch['name']} ---")
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()
            
            if not bake_store_cookie(page, branch["name"], branch["search"], CASHBUILD_PRODUCTS[0]["url"]):
                print("  [Error] Could not set store. Skipping branch.")
                context.close()
                continue
            
            for product in CASHBUILD_PRODUCTS:
                print(f"  -> {product['label']}")
                page.goto(product["url"].strip(), wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                
                if product.get("needs_store_select", False):
                    modal = page.query_selector("#storeSelectorModal")
                    if modal:
                        print("  [setup] Selecting store for this product...")
                        select_store(page, branch["search"])
                
                if page.query_selector("#storeSelectorModal"):
                    dismiss_modal(page)
                    page.wait_for_timeout(2000)
                
                price_zar = extract_price(page, product)
                
                if price_zar:
                    prev = get_previous_price(product["id"], branch["city"])
                    delta = round(((price_zar - prev["price_zar"]) / prev["price_zar"]) * 100, 2) if prev and prev.get("price_zar") else None
                    price_szl = push_price(product["id"], product["label"], branch["name"], branch["city"], price_zar, delta, available=True)
                    print(f"     ✅ SUCCESS: R{price_zar:.2f} (E{price_szl:.2f}) | Delta: {delta}%")
                else:
                    push_price(product["id"], product["label"], branch["name"], branch["city"], None, None, available=False)
                    print("     ⚠️  UNAVAILABLE")
                
                time.sleep(1)
            
            context.close()
            print()
        
        browser.close()
    
    print("\n" + "="*60)
    print("CASHBUILD SCRAPE COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    scrape()
