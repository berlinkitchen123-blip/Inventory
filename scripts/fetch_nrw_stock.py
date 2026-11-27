#!/usr/bin/env python3
"""Fetch NRW outlet stock from Apicbase and update stock-patch.json."""
import json, os, urllib.request, urllib.parse, sys, datetime
from pathlib import Path

TOKEN = os.environ.get("APICBASE_TOKEN", "")
BASE  = "https://api.apicbase.com/api/v2"
OUTLET_ID = "729210832720007"
STOCK_FILE = Path("data/stock-patch.json")

def api(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "User-Agent": "bellabona-nrw-planner/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}

def all_pages(path, params=None):
    params = dict(params or {})
    params["page_size"] = 200
    out, page = [], 1
    while True:
        params["page"] = page
        st, data = api(path, params)
        if st != 200:
            print(f"  ERROR {path} HTTP {st}: {data}")
            break
        rows = data.get("results", [])
        out.extend(rows)
        if not data.get("next") or not rows:
            break
        page += 1
    return out

if not TOKEN:
    sys.exit("APICBASE_TOKEN not set")

# --- Find the outlet ---
st, outlets_data = api("/accounts/outlets/")
print(f"Outlets endpoint: HTTP {st}")
if st == 200:
    outlets = outlets_data.get("results", [])
    nrw = next((o for o in outlets if str(o.get("id","")) == OUTLET_ID or
                str(o.get("pk","")) == OUTLET_ID), None)
    if nrw:
        print(f"NRW outlet found: {nrw.get('name','')} keys={sorted(nrw)[:15]}")
    else:
        ids = [str(o.get("id") or o.get("pk","?")) for o in outlets]
        print(f"NRW outlet NOT found. Available: {ids[:10]}")

# --- Try stock item endpoints ---
patterns = [
    f"/inventory/outlets/{OUTLET_ID}/stock_items/",
    f"/accounts/outlets/{OUTLET_ID}/stock_items/",
    f"/products/stock_items/?outlet_id={OUTLET_ID}",
    "/products/stock_items/",
]
working_path = None
working_data = None
for p in patterns:
    st2, d = api(p)
    cnt = len(d.get("results", [])) if isinstance(d, dict) else 0
    print(f"  {p} -> HTTP {st2}, count={cnt}")
    if st2 == 200 and cnt > 0 and working_path is None:
        working_path = p
        working_data = d

if working_path:
    print(f"\nUsing: {working_path}")
    all_items = all_pages(working_path)
    print(f"Total stock items: {len(all_items)}")
    if all_items:
        print(f"First item keys: {sorted(all_items[0])[:20]}")
        print(f"First item: {json.dumps(all_items[0], indent=2)[:500]}")
    
    # Update stock-patch.json
    if STOCK_FILE.exists():
        with open(STOCK_FILE) as f:
            patch = json.load(f)
        
        today = datetime.date.today().isoformat()
        patch["version"] = today
        patch["nrw_stock"]["week"] = today
        patch["nrw_stock"]["source"] = f"Apicbase API fetch {today}"
        
        # Map Apicbase items to our format
        updated = 0
        for item in all_items:
            name = item.get("name") or item.get("ingredient_name", "")
            qty = item.get("quantity") or item.get("current_quantity") or item.get("amount") or 0
            unit = item.get("unit") or item.get("storage_unit", "kg")
            # Match to stock-patch items (URL-decoded)
            for key, entry in patch["nrw_stock"]["items"].items():
                if name and entry["name"].lower() in name.lower():
                    entry["qty"] = float(qty)
                    entry["unit"] = str(unit).lower()
                    updated += 1
                    break
        
        print(f"\nUpdated {updated} items in stock-patch.json")
        with open(STOCK_FILE, "w") as f:
            json.dump(patch, f, indent=2, ensure_ascii=False)
        print("Saved stock-patch.json")
    else:
        print("stock-patch.json not found, printing raw data only")
        # Just show what we got
        for item in all_items[:20]:
            print(f"  {item.get('name','')} qty={item.get('quantity',item.get('current_quantity','?'))} unit={item.get('unit','?')}")
else:
    print("\nNo working stock items endpoint found. Need to investigate further.")
