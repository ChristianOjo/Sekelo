"""
Sekelo — Builders.co.za Scraper
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

# NUCLEAR URL CLEANING — Hardcode clean URLs
BUILDERS_PRODUCTS = [
    {"id": "bricks_builders", "label": "Dreamcast M140 Concrete Block", "url": "https://www.builders.co.za/Building-Materials/Bricks/Plaster-Bricks/Dreamcast-M140-Concrete-Block-390-x-140-x-190-mm/p/000000000000644862", "ajax_wait": 15, "min_price": 10, "max_price": 25},
    {"id": "riversand", "label": "Builders River Sand 40kg", "url": "https://www.builders.co.za/Building-Materials/Stones-Sands-and-Premix/Premixes/Builders-River-Sand-40-kg-646214---Exclusive-to-Builders/p/000000000000646214", "ajax_wait": 15, "min_price": 30, "max_price": 80},
    {"id": "cement_builders", "label": "PPC Surebuild 42.5N 50kg", "url": "https://www.builders.co.za/Building-Materials/Cements/Cement/PPC-Surebuild-42-5N-Cement--50kg--627933/p/000000000000627933", "ajax_wait": 15, "min_price": 80, "max_price": 150},
    {"id": "timber_builders", "label": "SA Pine Brandering PAR 38x38x4200mm", "url": "https://www.builders.co.za/Building-Materials/Boards-and-Sheeting/Timber/York-Timbers-SA-Pine-Brandering-PAR-Untreated-Timber-38-x-38-x-4200-mm/p/000000000000005476", "ajax_wait": 15, "min_price": 50, "max_price": 150},
]

# ── SUPABASE ────────────────────────────────────────────────────

def get_previous_price(material_id):
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, params={
            "material_id": f"eq.{material_id}",
            "city": f"eq.National",
            "source": f"eq.builders",
            "order": "timestamp.desc",
            "limit": "1",
            "select": "price_zar"
        })
        data = res.json()
        return data[0] if data else None
    except Exception:
        return None


def push_price(material_id, material, price_zar, delta_24h, available=True):
    price_szl = round(price_zar * ZAR_TO_SZL * (1 + BORDER_PREMIUM), 2) if price_zar else None
    payload = {
        "material_id": material_id,
        "material": material,
        "branch": "Builders Online",
        "city": "National",
        "source": "builders",
        "price_zar": price_zar,
        "price_szl": price_szl,
        "delta_24h": delta_24h,
        "currency": "ZAR",
        "available": available
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/prices", headers=HEADERS, json=payload)
    return price_szl

# ── BROWSER ─────────────────────────────────────────────────────

def extract_price(page, product, max_retries=2):
    price_selectors = ["span.price", ".product-price", "[data-price]", ".sale-price", ".regular-price", "span[class*='price']"]
    ajax_wait = product.get("ajax_wait", 10)
    min_price = product.get("min_price", 0)
    max_price = product.get("max_price", 9999)
    product_id = product.get("id", "unknown")
    
    for retry in range(max_retries):
        try:
            page.wait_for_timeout(ajax_wait * 1000)
            try:
                page.wait_for_selector("span.price, .product-price", timeout=8000)
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
    print(f"SEKELO — BUILDERS.CO.ZA SCRAPER")
    print(f"Start: {datetime.now()}")
    print(f"{'='*60}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        
        print("  [setup] National pricing (no store select)\n")
        
        for product in BUILDERS_PRODUCTS:
            print(f"  -> {product['label']}")
            try:
                # NUCLEAR CLEANING — Multiple methods
                raw_url = product["url"]
                clean_url = raw_url.strip().rstrip().replace(" ", "").replace("%20", "")
                print(f"     [debug] URL length: {len(clean_url)}")
                
                page.goto(clean_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                
                price_zar = extract_price(page, product)
                
                if price_zar:
                    prev = get_previous_price(product["id"])
                    delta = round(((price_zar - prev["price_zar"]) / prev["price_zar"]) * 100, 2) if prev and prev.get("price_zar") else None
                    price_szl = push_price(product["id"], product["label"], price_zar, delta, available=True)
                    print(f"     ✅ SUCCESS: R{price_zar:.2f} (E{price_szl:.2f}) | Delta: {delta}%")
                else:
                    push_price(product["id"], product["label"], None, None, available=False)
                    print("     ⚠️  UNAVAILABLE")
                
                time.sleep(1)
            except Exception as e:
                print(f"     ❌ ERROR: {e}")
                push_price(product["id"], product["label"], None, None, available=False)
        
        context.close()
        browser.close()
    
    print("\n" + "="*60)
    print("BUILDERS SCRAPE COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    scrape()
