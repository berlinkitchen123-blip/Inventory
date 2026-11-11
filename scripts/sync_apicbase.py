"""Copy the Apicbase library into Firebase so the planner can read it without a token.

Writes under `apicbase/` in the stock-f24 Realtime Database, beside `nrw-stock-planner/`.
Nothing here is ever committed to the repository: supplier prices stay behind the
@bellabona.com login.

    APICBASE_TOKEN=... FIREBASE_SA='{...}' python scripts/sync_apicbase.py
Options:
    --full              ignore the last sync time and re-pull everything
    --max-recipes N     stop after N recipe details (smoke test)
    --dry-run           fetch and report, write nothing

The first run pulls ~1,960 requests, about 20 minutes at the 100/min limit. Later runs
use modified_date__gt and finish in seconds.
"""
import argparse
import datetime as dt
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = (os.getenv("APICBASE_BASE") or "https://api.apicbase.com/api/v2").rstrip("/")
DB = (os.getenv("FIREBASE_DB_URL")
      or "https://stock-f24-default-rtdb.europe-west1.firebasedatabase.app").rstrip("/")
ROOT = "apicbase"
PAGE = 200           # the API caps page_size at 200
RATE = 90            # requests a minute, under the API's limit of 100
WORKERS = 3          # parallel recipe detail fetches; the limiter still caps the rate
CHUNK = 150          # records per Firebase write
SAVE_EVERY = 300     # write recipes to Firebase this often, so a timeout loses little

_stamps, _lock = [], threading.Lock()


def throttle():
    """Let through at most RATE requests in any rolling minute, across all threads."""
    while True:
        with _lock:
            now = time.time()
            while _stamps and now - _stamps[0] > 60:
                _stamps.pop(0)
            if len(_stamps) < RATE:
                _stamps.append(now)
                return
            sleep = 60 - (now - _stamps[0]) + 0.05
        time.sleep(max(sleep, 0.05))


def api(path, params=None, tries=4):
    """GET one Apicbase page, honouring the rate limit."""
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(tries):
        throttle()
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {os.environ['APICBASE_TOKEN']}",
            "Accept": "application/json",
            "User-Agent": "bellabona-nrw-planner/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float((e.headers or {}).get("X-RateLimit-Wait") or 20))
                continue
            if e.code in (500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"{path} -> HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        except Exception as e:
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"{path} -> {type(e).__name__}: {e}")
    raise RuntimeError(f"{path} -> gave up after {tries} tries")


def pages(path, params=None):
    """Every record of a list endpoint."""
    params = dict(params or {})
    params["page_size"] = PAGE
    page, out = 1, []
    while True:
        params["page"] = page
        data = api(path, params)
        rows = data.get("results") or []
        out.extend(rows)
        if not data.get("next") or not rows:
            return out
        page += 1


# ---------------------------------------------------------------- Firebase

def fb_token():
    """OAuth2 access token for the service account in FIREBASE_SA."""
    from google.oauth2 import service_account
    import google.auth.transport.requests
    info = json.loads(os.environ["FIREBASE_SA"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=[
        "https://www.googleapis.com/auth/firebase.database",
        "https://www.googleapis.com/auth/userinfo.email",
    ])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def fb(method, path, payload=None, token=None):
    url = f"{DB}/{path}.json"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw and raw != "null" else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Firebase {method} {path} -> HTTP {e.code}: "
                           f"{e.read().decode('utf-8','replace')[:200]}")


def fb_write(node, mapping, token, label):
    """PATCH a dict into one node, in chunks Firebase is comfortable with."""
    items = list(mapping.items())
    for i in range(0, len(items), CHUNK):
        fb("PATCH", node, dict(items[i:i + CHUNK]), token)
    print(f"  wrote {len(items):>5} {label}")


# ---------------------------------------------------------------- shaping

def ident(url_or_id):
    """The trailing id out of an Apicbase resource URL."""
    if not url_or_id:
        return None
    s = str(url_or_id).rstrip("/")
    return s.rsplit("/", 1)[-1] or None


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 4)


def recipe_row(r, detail):
    """One recipe as the planner needs it."""
    lines = []
    for ln in (detail.get("ingredients") or []):
        sub = ident(ln.get("subrecipe"))
        ing = ident(ln.get("ingredient"))
        if not sub and not ing:
            continue
        lines.append({
            "name": ln.get("name") or "",
            "qty": num(ln.get("quantity")) or 0,
            "unit": (ln.get("unit") or "").strip(),
            "waste": num(ln.get("waste_percentage")) or 0,
            **({"sub": sub} if sub else {"ing": ing}),
        })
    return {
        "name": r.get("name") or "",
        "persons": num(r.get("persons")) or 1,
        "netWeight": num(r.get("net_weight")),
        "netWeightUnit": r.get("net_weight_unit") or "",
        "semi": bool(r.get("is_semi_finished_product")),
        "stockable": bool(r.get("is_stockable_recipe")),
        "category": r.get("category") or "",
        "modified": r.get("modified_date") or "",
        "lines": lines,
    }


def build_packs(ingredients, stock_items, packages):
    """ingredient id -> the cheapest orderable package, with supplier and pack size."""
    by_stock = {}
    for p in packages:
        sid = str((p.get("stock_item") or {}).get("id") or "")
        if sid:
            by_stock.setdefault(sid, []).append(p)
    out = {}
    for si in stock_items:
        ing = si.get("main_ingredient_id")
        if not ing or not si.get("active", True):
            continue
        pd = si.get("package_description") or {}
        for p in by_stock.get(str(si.get("id")), []):
            if not p.get("orderable") or not p.get("active", True):
                continue
            price = num(p.get("average_price_per_package"))
            cur = out.get(str(ing))
            if cur and cur.get("price") is not None and (price is None or price >= cur["price"]):
                continue
            out[str(ing)] = {
                "stockItem": si.get("name") or "",
                "content": si.get("content") or "",
                "packQty": num(pd.get("quantity")),
                "packUnit": pd.get("unit") or pd.get("base_unit") or "",
                "price": price,
                "supplier": (p.get("supplier") or {}).get("name") or "",
                "article": p.get("supplier_article_number") or "",
                "returnable": bool(si.get("returnable")),
            }
    for ing in ingredients:                       # ingredients with no orderable pack
        out.setdefault(str(ing.get("id")), {"stockItem": "", "supplier": "", "price": None})
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--max-recipes", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for key in ("APICBASE_TOKEN",) + (() if args.dry_run else ("FIREBASE_SA",)):
        if not os.getenv(key):
            sys.exit(f"{key} is not set.")

    token = None if args.dry_run else fb_token()
    since = None
    if not args.full and not args.dry_run:
        meta = fb("GET", f"{ROOT}/meta", None, token) or {}
        since = meta.get("generated")
    print(f"mode: {'full' if not since else 'changes since ' + since}")

    outlets = {str(o["id"]): o.get("name") or "" for o in pages("/accounts/outlets/")}
    print(f"  outlets        {len(outlets)}")

    filt = {"modified_date__gt": since} if since else {}
    recipes = pages("/products/recipes/", filt)
    ingredients = pages("/products/ingredients/", filt)
    stock_items = pages("/products/stock_items/")
    packages = pages("/products/supplier_packages/")
    menus = pages("/products/menus/", filt)
    print(f"  recipes        {len(recipes)} to refresh")
    print(f"  ingredients    {len(ingredients)}")
    print(f"  stock items    {len(stock_items)}")
    print(f"  packages       {len(packages)}")
    print(f"  menus          {len(menus)}")

    todo = recipes[:args.max_recipes] if args.max_recipes else recipes
    print(f"  fetching {len(todo)} recipe details with {WORKERS} workers "
          f"(~{len(todo) / RATE:.0f} min at {RATE}/min)…")
    if not since and not args.dry_run:
        fb("DELETE", f"{ROOT}/recipes", None, token)   # clear before a full rebuild
    recipe_rows, failed, done, pending = {}, 0, 0, {}

    def one(r):
        try:
            return str(r["id"]), recipe_row(r, api(f"/products/recipes/{r['id']}/"))
        except RuntimeError as e:
            print(f"    skipped recipe {r['id']}: {e}"[:160])
            return str(r["id"]), None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for rid, row in pool.map(one, todo):
            done += 1
            if row is None:
                failed += 1
            else:
                recipe_rows[rid] = row
                pending[rid] = row
            if len(pending) >= SAVE_EVERY and not args.dry_run:
                fb_write(f"{ROOT}/recipes", pending, token, f"recipes ({done}/{len(todo)})")
                pending = {}
            elif done % 200 == 0:
                print(f"    {done}/{len(todo)}")
    if pending and not args.dry_run:
        fb_write(f"{ROOT}/recipes", pending, token, f"recipes ({done}/{len(todo)})")

    ing_rows = {str(i["id"]): {"name": i.get("name") or "",
                               "category": i.get("category") or "",
                               "inUse": bool(i.get("in_use", True))} for i in ingredients}
    menu_rows = {str(m["id"]): {
        "name": m.get("name") or "", "from": (m.get("starting_date") or "")[:10],
        "to": (m.get("ending_date") or "")[:10],
        "recipes": [str(ident(c)) for c in (m.get("courses") or []) if ident(c)],
    } for m in menus}
    packs = build_packs(ingredients, stock_items, packages)

    print(f"\n  recipes with lines {len(recipe_rows)} ({failed} failed)")
    print(f"  packs (ingredient -> cheapest orderable) {len(packs)}")
    if args.dry_run:
        sample = next(iter(recipe_rows.values()), None)
        print("\ndry run, nothing written. One recipe's line count: "
              f"{len(sample['lines']) if sample else 'n/a'}")
        return

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    print()
    fb_write(f"{ROOT}/ingredients", ing_rows, token, "ingredients")
    fb_write(f"{ROOT}/packs", packs, token, "packs")
    fb_write(f"{ROOT}/menus", menu_rows, token, "menus")
    fb("PUT", f"{ROOT}/outlets", outlets, token)
    fb("PUT", f"{ROOT}/meta", {
        "generated": now, "recipes": len(recipe_rows), "ingredients": len(ing_rows),
        "packs": len(packs), "menus": len(menu_rows), "failed": failed,
        "mode": "full" if not since else "incremental"}, token)
    print(f"\nDone at {now}.")


if __name__ == "__main__":
    main()
