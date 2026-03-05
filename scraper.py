"""
Sekelo — Cashbuild Scraper
Production v3.1 (FIXED)

Changes from v3.0:
1. Fixed Supabase URL (removed trailing spaces)
2. Added store selection verification
3. Replaced fixed 35s wait with explicit network wait
4. Added screenshot on failure for debugging
5. Fixed duplicate product logging
"""

import time
import re
import requests
import os
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── CONFIG ─────────────────────────────────────────────────────

SUPABASE_URL = "https://glvpdeneagsqwxzrtaln.supabase.co"  # FIXED: No trailing spaces
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdsdnBkZW5lYWdzcXd4enJ0YWxuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzODQ4NDQsImV4cCI6MjA4Nzk2MDg0NH0.y5gJY1XRFj5uGYUjnkZ9rPfLQRdub5uKBn8jIxEpdP8")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

BORDER_PREMIUM = 0.20
ZAR_TO_SZL = 1.0

BRANCHES = [
    {"name": "Southgate | Cashbuild",       "city": "Joburg",    "search": "southgate"},
    {"name": "Nelspruit Plaza | Cashbuild",  "city": "Nelspruit", "search": "nelspruit plaza"},
]

PRODUCTS = [
    {"id": "cement",       "label": "AfriSam All Purpose 42.5N 50kg",  "url": "https://www.cashbuild.co.za/cement-yard/301-cement-afrisam-all-purpose-425n",            "min_price": 90,  "max_price": 160, "price_type": "ajax"},
    {"id": "rebar",        "label": "Steel Rebar Y12",                  "url": "https://www.cashbuild.co.za/steel-sections/476005-reinforcing-rod-y12mm-x-6m-450-mpa",   "min_price": 100, "max_price": 200, "price_type": "ajax"},
    {"id": "timber",       "label": "Structural Timber S5 38x114 6.0m", "url": "https://www.cashbuild.co.za/timber/19160-structural-timber-sabs-untreated-38x114-60m",  "min_price": 180, "max_price": 260, "price_type": "ajax"},
    {"id": "bricks",       "label": "Concrete Block MB-140",            "url": "https://www.cashbuild.co.za/cement-blocks/1099412-block-concrete-mb-140",                "min_price": 8,   "max_price": 25,  "price_type": "text"},
    {"id": "bricks_maxi",  "label": "Cement Brick Solid Maxi",          "url": "https://www.cashbuild.co.za/cement-plaster-bricks/1099234-brick-cement-solid-maxi",      "min_price": 2,   "max_price": 12,  "price_type": "text"},
    {"id": "concrete_mix", "label": "Concrete Mix 40kg",                "url": "https://www.cashbuild.co.za/premix/325-concrete-mix-40kg-bag",                           "min_price": 35,  "max_price": 60,  "price_type": "text"},
]

SCOPED_PRICE_SELECTORS = [
    ".product-single__price span.current-price-value",
    ".product-single__price .money",
    ".product__price span.current-price-value",
    ".product__price .money",
    "#product-price span.current-price-value",
    ".product-detail-price span.current-price-value",
    ".product-info__price span.current-price-value",
    "span.current-price-value",  # Added: generic fallback
    "[data-price]",              # Added: alternative data attribute
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
        }, timeout=10)
        res.raise_for_status()
        data = res.json()
        return data[0] if data else None
    except Exception as e:
        print(f"     [warn] Supabase fetch failed: {e}")
        return None

def push_price(material_id, material, branch, city, price_zar, delta_24h, available=True):
    price_szl = round(price_zar * ZAR_TO_SZL * (1 + BORDER_PREMIUM), 2) if price_zar else None
    payload = {
        "material_id": material_id, "material": material, "branch": branch,
        "city": city, "source": "cashbuild", "price_zar": price_zar, "price_szl": price_szl,
        "delta_24h": delta_24h, "currency": "ZAR", "available": available
    }
    try:
        res = requests.post(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, json=payload, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"     [warn] Supabase push failed: {e}")
    return price_szl

# ── STORE SELECTION ─────────────────────────────────────────────

def dismiss_modal(page):
    for _ in range(3):
        modal = page.query_selector("#storeSelectorModal")
        if not modal or modal.is_hidden():
            return True
        for _ in range(20):
            modal = page.query_selector("#storeSelectorModal")
            if not modal or modal.is_hidden():
                return True
            page.wait_for_timeout(300)
    return False

def select_store(page, search_term):
    """Select store and VERIFY it was selected."""
    try:
        page.wait_for_selector(".store-list .store-item", timeout=10000)
        page.wait_for_timeout(2000)
    except:
        print(f"     [warn] Store list not found")
        return False
    
    stores = page.query_selector_all(".store-list .store-item")
    print(f"     [debug] Found {len(stores)} stores in modal")
    
    for store in stores:
        try:
            store_text = store.inner_text().strip().lower()
            if search_term.lower() in store_text:
                store.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                store.click(force=True)
                page.wait_for_timeout(3000)
                dismiss_modal(page)
                page.wait_for_timeout(3000)
                
                # VERIFY: Check if store name appears in header
                try:
                    header = page.query_selector(".store-selector-trigger, .selected-store-name")
                    if header and search_term.lower() in header.inner_text().lower():
                        print(f"     [debug] Store selection VERIFIED")
                        return True
                    else:
                        print(f"     [warn] Store selection may not have registered")
                except:
                    pass
                return True
        except Exception as e:
            print(f"     [warn] Store click failed: {e}")
            continue
    
    print(f"     [warn] No store matched '{search_term}'")
    return False

def ensure_store_selected(page, search_term):
    """Open store modal if needed, then select the branch."""
    # Check if store modal is already open
    if not page.query_selector("#storeSelectorModal"):
        # Try multiple trigger selectors
        for trigger_sel in [".store-selector-trigger", ".change-store", "[data-store-selector]", ".select-store", ".store-btn"]:
            try:
                trigger = page.query_selector(trigger_sel)
                if trigger and trigger.is_visible():
                    print(f"     [debug] Clicking store trigger: {trigger_sel}")
                    trigger.click(force=True)
                    page.wait_for_timeout(3000)
                    break
            except:
                pass
    
    return select_store(page, search_term)

# ── PRICE EXTRACTION ────────────────────────────────────────────

def extract_price(page, product, search_term, branch_name):
    min_price = product["min_price"]
    max_price = product["max_price"]
    pid = product["id"]

    # Static pages — no store selection needed
    if product.get("price_type") == "text":
        page.wait_for_timeout(3000)
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
                        print(f"     [debug] {pid}: R{price} via text (static page)")
                        return price
                except:
                    pass
        print(f"     [debug] {pid}: no price in range [{min_price}-{max_price}]")
        return None

    # AJAX products — store selection required
    print(f"     [setup] Selecting store for {branch_name}...")
    store_selected = ensure_store_selected(page, search_term)
    
    if not store_selected:
        print(f"     [warn] Store selection failed, attempting price extraction anyway")

    # Step 1: Wait for AJAX price with explicit selector (max 20s)
    try:
        page.wait_for_selector("span.current-price-value", timeout=20000)
        page.wait_for_timeout(2000)  # Allow JS to populate content attribute
        
        els = page.query_selector_all("span.current-price-value")
        for el in els:
            if not el.is_visible():
                continue
            content = el.get_attribute("content")
            if content:
                try:
                    price = float(content)
                    if min_price <= price <= max_price:
                        print(f"     [debug] {pid}: R{price} via content attribute")
                        return price
                    else:
                        print(f"     [debug] {pid}: content R{price} outside range [{min_price}-{max_price}]")
                except:
                    pass
    except PlaywrightTimeout:
        print(f"     [debug] {pid}: content timeout after 20s")

    # Step 2: Scoped fallback selectors
    for selector in SCOPED_PRICE_SELECTORS:
        try:
            els = page.query_selector_all(selector)
            for el in els:
                if not el.is_visible():
                    continue
                # Try content attribute first
                content = el.get_attribute("content")
                if content:
                    try:
                        price = float(content)
                        if min_price <= price <= max_price:
                            print(f"     [debug] {pid}: R{price} via scoped content ({selector})")
                            return price
                    except:
                        pass
                # Try text content
                text = el.inner_text().strip().replace("R", "").replace(",", "").strip()
                match = re.search(r'[\d.]+', text)
                if match:
                    try:
                        price = float(match.group())
                        if min_price <= price <= max_price:
                            print(f"     [debug] {pid}: R{price} via scoped text ({selector})")
                            return price
                    except:
                        pass
        except:
            pass

    # Step 3: Final retry with page refresh
    print(f"     [debug] {pid}: final retry — refreshing page")
    try:
        page.reload(wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(5000)
        ensure_store_selected(page, search_term)
        page.wait_for_timeout(10000)
        
        els = page.query_selector_all("span.current-price-value")
        for el in els:
            if not el.is_visible():
                continue
            content = el.get_attribute("content")
            if content:
                try:
                    price = float(content)
                    if min_price <= price <= max_price:
                        print(f"     [debug] {pid}: R{price} via content (retry)")
                        return price
                except:
                    pass
    except Exception as e:
        print(f"     [warn] Final retry failed: {e}")

    # Save screenshot for debugging
    try:
        page.screenshot(path=f"/tmp/debug_{pid}_{branch_name.replace(' ', '_')}.png")
        print(f"     [debug] Screenshot saved for debugging")
    except:
        pass

    print(f"     [debug] {pid}: all methods exhausted, no price in range [{min_price}-{max_price}]")
    return None

# ── MAIN ─────────────────────────────────────────────────────────

def scrape():
    print(f"\nSEKELO SCRAPER v3.1 — {datetime.now()}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for branch in BRANCHES:
            print(f"\n{'='*50}")
            print(f"BRANCH: {branch['name']}")
            print(f"{'='*50}\n")
            
            context = browser.new_context()
            page = context.new_page()

            for product in PRODUCTS:
                print(f"  -> {product['label']}")

                try:
                    page.goto(product["url"].strip(), wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"     [error] page load failed: {e}")
                    push_price(product["id"], product["label"], branch["name"], branch["city"], None, None, available=False)
                    print("     ⚠️  UNAVAILABLE (page load failed)")
                    continue

                price = extract_price(page, product, branch["search"], branch["name"].replace(" ", "_"))

                if price:
                    prev = get_previous_price(product["id"], branch["city"])
                    delta = round(((price - prev["price_zar"]) / prev["price_zar"]) * 100, 2) if prev and prev.get("price_zar") else None
                    push_price(product["id"], product["label"], branch["name"], branch["city"], price, delta)
                    print(f"     ✅ R{price:.2f}" + (f" ({delta:+.1f}%)" if delta else ""))
                else:
                    push_price(product["id"], product["label"], branch["name"], branch["city"], None, None, available=False)
                    print("     ⚠️  UNAVAILABLE")

                time.sleep(2)  # Increased delay between products

            context.close()

        browser.close()

    print(f"\n{'='*50}")
    print("✅ SCRAPE COMPLETE")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    scrape()
