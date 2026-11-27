"""
Fetch NRW outlet stock from Apicbase, update data/stock-patch.json.
Endpoint confirmed: /inventory/outlets/{OUTLET_ID}/stock_items/
Bug fixed: do NOT send 'page' param — it hangs; endpoint returns all data at once.
"""
import json, os, sys, urllib.request, urllib.parse
from pathlib import Path

TOKEN    = os.environ.get("APICBASE_TOKEN", "")
BASE     = "https://api.apicbase.com/api/v2"
OUTLET_ID = "729210832720007"
STOCK_FILE = Path("data/stock-patch.json")

if not TOKEN:
    print("ERROR: APICBASE_TOKEN not set", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "bellabona-nrw-planner/1.0",
    "Accept": "application/json",
}

def api_get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode())

# --- 1. Fetch stock items (no page param — it hangs) ---
print("Fetching stock items for NRW outlet...")
st, data = api_get(f"/inventory/outlets/{OUTLET_ID}/stock_items/")
print(f"HTTP {st}")

# Understand the response structure
if isinstance(data, dict):
    top_keys = list(data.keys())[:20]
    print(f"Response keys: {top_keys}")
    # Check common pagination fields
    for k in ("count", "next", "previous", "results", "data", "items", "stock_items"):
        if k in data:
            v = data[k]
            print(f"  [{k}]: {repr(v)[:200]}")
elif isinstance(data, list):
    print(f"Response is a list of {len(data)} items")
    if data:
        print(f"  First item keys: {list(data[0].keys())[:20]}")
        print(f"  First item: {json.dumps(data[0])[:400]}")

# Extract items list
items_list = None
if isinstance(data, list):
    items_list = data
elif isinstance(data, dict):
    for k in ("results", "data", "items", "stock_items"):
        if k in data and isinstance(data[k], list):
            items_list = data[k]
            print(f"Items under key '{k}': {len(items_list)}")
            break

if items_list is None:
    print("Could not find items list in response. Full response:")
    print(json.dumps(data)[:2000])
    sys.exit(1)

# Handle pagination via 'next' URL if present
if isinstance(data, dict) and data.get("next"):
    next_url = data["next"]
    print(f"Pagination detected, fetching next pages via 'next' URL...")
    page_count = 1
    while next_url:
        req = urllib.request.Request(next_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            page_data = json.loads(r.read().decode())
        batch = page_data.get("results", [])
        items_list.extend(batch)
        next_url = page_data.get("next")
        page_count += 1
        print(f"  Page {page_count}: +{len(batch)} items (total {len(items_list)})")
        if page_count > 50:
            break

print(f"\nTotal stock items fetched: {len(items_list)}")

# Show structure of first item
if items_list:
    first = items_list[0]
    print(f"Sample item keys: {list(first.keys())}")
    print(f"Sample item: {json.dumps(first)[:600]}")

# --- 2. Load stock-patch.json ---
if not STOCK_FILE.exists():
    print(f"ERROR: {STOCK_FILE} not found", file=sys.stderr)
    sys.exit(1)

with open(STOCK_FILE) as f:
    patch = json.load(f)

stock_items = patch.get("nrw_stock", {}).get("items", {})
print(f"\nstock-patch.json has {len(stock_items)} items")
print(f"Sample keys: {list(stock_items.keys())[:5]}")

# --- 3. Build name->qty mapping from API ---
# Figure out the name and qty field names
if items_list:
    sample = items_list[0]
    name_field = None
    qty_field  = None
    for nf in ("name", "ingredient_name", "product_name", "title", "article_name"):
        if nf in sample:
            name_field = nf
            break
    for qf in ("quantity", "qty", "stock_quantity", "current_qty", "current_quantity", "amount", "value"):
        if qf in sample:
            qty_field = qf
            break
    print(f"\nName field: {name_field}, Qty field: {qty_field}")

    # Build lookup
    api_stock = {}
    for item in items_list:
        name = item.get(name_field, "") if name_field else ""
        qty  = item.get(qty_field, 0)  if qty_field  else 0
        if name:
            api_stock[name] = qty
            # Also try URL-encoded version
            encoded = urllib.parse.quote(name, safe='')
            api_stock[encoded] = qty

    print(f"Built lookup with {len(api_stock)} name->qty entries")
    print("Sample API stock (first 10):")
    for k, v in list(api_stock.items())[:10]:
        print(f"  {k!r}: {v}")

    # --- 4. Update stock-patch.json ---
    matched = []
    unmatched_patch = []

    for key, item_data in stock_items.items():
        # key is URL-encoded, e.g. "Chicken%20Breast"
        decoded = urllib.parse.unquote(key)
        new_qty = None
        if key in api_stock:
            new_qty = api_stock[key]
        elif decoded in api_stock:
            new_qty = api_stock[decoded]
        else:
            # Try case-insensitive
            decoded_lower = decoded.lower()
            for api_name, api_qty in api_stock.items():
                if api_name.lower() == decoded_lower:
                    new_qty = api_qty
                    break

        if new_qty is not None:
            old_qty = item_data.get("qty", "?")
            item_data["qty"] = new_qty
            matched.append(f"  {decoded}: {old_qty} → {new_qty}")
        else:
            unmatched_patch.append(decoded)

    print(f"\nMatched: {len(matched)}, Unmatched: {len(unmatched_patch)}")
    print("Updated quantities:")
    for m in matched[:30]:
        print(m)
    if unmatched_patch:
        print(f"\nNOT MATCHED in API ({len(unmatched_patch)}):")
        for u in unmatched_patch[:20]:
            print(f"  {u}")

    # Unmatched API items (not in patch)
    decoded_patch = {urllib.parse.unquote(k).lower() for k in stock_items}
    unmatched_api = [n for n in api_stock if n.lower() not in decoded_patch and "%" not in n]
    if unmatched_api:
        print(f"\nIn API but not in patch ({len(unmatched_api)}):")
        for n in unmatched_api[:20]:
            print(f"  {n!r}: {api_stock[n]}")

    # --- 5. Save updated file ---
    import datetime
    patch["nrw_stock"]["version"] = datetime.date.today().isoformat()
    with open(STOCK_FILE, "w") as f:
        json.dump(patch, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {STOCK_FILE} (version {patch['nrw_stock']['version']})")

