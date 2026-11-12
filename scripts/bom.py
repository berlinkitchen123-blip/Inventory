"""Turn a list of dishes and portions into a supplier order, using the Apicbase BOM.

    APICBASE_TOKEN=... python scripts/bom.py --demand data/catering-demand.json
Options:
    --outlet NAME     outlet to cost against (default NRW)
    --prices          include prices in the printed list (off by default: the
                      Actions log of a public repository is public)

Stock is never subtracted. The Apicbase stock figures are not kept up to date,
so the quantities printed are the full requirement.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE = (os.getenv("APICBASE_BASE") or "https://api.apicbase.com/api/v2").rstrip("/")
DB = (os.getenv("FIREBASE_DB_URL")
      or "https://stock-f24-default-rtdb.europe-west1.firebasedatabase.app").rstrip("/")
PAGE, GAP = 200, 0.7
MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "dish-map.json")
_last = [0.0]


def fb_token():
    from google.oauth2 import service_account
    import google.auth.transport.requests
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["FIREBASE_SA"]), scopes=[
            "https://www.googleapis.com/auth/firebase.database",
            "https://www.googleapis.com/auth/userinfo.email"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def fb_put(path, payload, token):
    req = urllib.request.Request(f"{DB}/{path}.json", data=json.dumps(payload).encode("utf-8"),
                                 method="PUT", headers={"Authorization": f"Bearer {token}",
                                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Firebase PUT {path} -> {e.code}: {e.read().decode('utf-8','replace')[:200]}")


def api(path, params=None, body=None, tries=4):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = None if body is None else json.dumps(body).encode("utf-8")
    for attempt in range(tries):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {os.environ['APICBASE_TOKEN']}",
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "bellabona-nrw-planner/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429:
                time.sleep(float((e.headers or {}).get("X-RateLimit-Wait") or 20)); continue
            if e.code in (500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(3 * (attempt + 1)); continue
            raise RuntimeError(f"{path} -> HTTP {e.code}: {detail}")
        except Exception as e:
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1)); continue
            raise RuntimeError(f"{path} -> {type(e).__name__}: {e}")


def pages(path, params=None):
    params = dict(params or {}); params["page_size"] = PAGE
    page, out = 1, []
    while True:
        params["page"] = page
        d = api(path, params)
        rows = d.get("results") or []
        out.extend(rows)
        if not d.get("next") or not rows:
            return out
        page += 1


STOP = {"with", "and", "the", "a", "of", "in", "on", "for", "halves", "portions",
        "mini", "style", "bite", "bites", "cup", "cups", "salad", "sandwich"}


def norm(s):
    """Fold a dish name so small differences stop mattering."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def load_map():
    """data/dish-map.json: a dish name a human has already tied to a recipe id."""
    try:
        raw = json.load(open(MAP_FILE, encoding="utf-8"))
    except FileNotFoundError:
        return {}
    out = {}
    for dish, val in (raw.get("map") or raw).items():
        if isinstance(val, dict):
            rid = val.get("id")
        else:
            rid = val
        if rid:
            out[norm(dish)] = str(rid)
    return out


def resolve(demand, recipes, prefer_ct=False):
    """Dish name -> recipe. The map first, then an exact name. Never a guess.

    prefer_ct: catering. The catering version of a dish is kept in Apicbase
    under the same name with " - CT" on the end, and that is the one to cost,
    so it is tried before the plain name. Outside catering the CT copies are
    ignored, which is the rule everywhere else in this repository.

    There used to be a contained-substring fallback here. It silently tied
    "Caesar Salad with Chicken" to a recipe called "Chicken" and both couscous
    cups to a bulk batch called "CousCous", so the order came out wrong while
    looking complete. A dish that is not in the map and does not match a name
    exactly is now reported as unmatched, and is left out of the order.
    """
    by_norm, by_id, matched, unmatched = {}, {}, [], []
    for r in recipes:
        by_norm.setdefault(norm(r.get("name")), []).append(r)
        by_id[str(r.get("id"))] = r
    dish_map = load_map()
    for row in demand:
        key = norm(row["dish"])
        rid = dish_map.get(key)
        if rid and rid in by_id:
            r = by_id[rid]
            matched.append({**row, "id": r["id"], "matched": r.get("name"), "how": "mapped"})
            continue
        if rid:
            unmatched.append({**row, "candidates": [],
                              "why": f"dish-map points at recipe {rid}, which is not in the library"})
            continue
        hits, how = [], "exact"
        if prefer_ct:
            hits = by_norm.get(key + " ct") or []
            how = "exact CT"
        if not hits:
            hits = [h for h in (by_norm.get(key) or []) if not norm(h.get("name")).endswith(" ct")]
            how = "exact"
        if len(hits) == 1:
            matched.append({**row, "id": hits[0]["id"], "matched": hits[0].get("name"), "how": how})
            continue
        want = set(w for w in key.split() if w not in STOP and len(w) > 2)
        scored = []
        for k, rs in by_norm.items():
            if not k or (k.endswith(" ct") and not prefer_ct):
                continue
            have = set(k.split())
            shared = len(want & have)
            if shared:
                scored.append((shared / max(1, len(want | have)), rs[0].get("id"), rs[0].get("name")))
        scored.sort(reverse=True)
        unmatched.append({**row,
                          "candidates": [f"{i}  {n}" for _, i, n in scored[:8]],
                          "why": "two recipes share this name" if len(hits) > 1 else "no exact match"})
    return matched, unmatched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demand", required=True)
    ap.add_argument("--outlet", default="NRW")
    ap.add_argument("--prices", action="store_true")
    ap.add_argument("--recipes", action="store_true",
                    help="also read each matched recipe, to show what is inside it")
    ap.add_argument("--firebase", action="store_true",
                    help="also write the order into Firebase for the planner to show")
    args = ap.parse_args()
    if not os.getenv("APICBASE_TOKEN"):
        sys.exit("APICBASE_TOKEN is not set.")

    spec = json.load(open(args.demand, encoding="utf-8"))
    demand = spec["demand"]
    print(f"{spec.get('week','?')} · {spec.get('range','')} · "
          f"{len(demand)} dishes · {sum(d['servings'] for d in demand)} portions\n")

    outlets = pages("/accounts/outlets/")
    outlet = next((o for o in outlets if args.outlet.lower() in (o.get("name") or "").lower()), None)
    if not outlet:
        sys.exit(f"No outlet matching '{args.outlet}'. Found: {[o.get('name') for o in outlets]}")
    print(f"outlet: {outlet.get('name')} (id {outlet['id']})")

    recipes = pages("/products/recipes/")
    print(f"recipes in library: {len(recipes)}")
    prefer_ct = bool(spec.get("preferCT"))
    if prefer_ct:
        print("catering: the '- CT' version of a recipe is preferred over the plain one")
    matched, unmatched = resolve(demand, recipes, prefer_ct)
    print(f"matched {len(matched)} of {len(demand)} dishes "
          f"({sum(1 for m in matched if m['how'] == 'mapped')} from data/dish-map.json, "
          f"{sum(1 for m in matched if m['how'].startswith('exact'))} by exact name)\n")
    print("WHAT EACH DISH WAS TIED TO - check this before ordering")
    print("-" * 72)
    for m in matched:
        flag = "" if norm(m["dish"]) == norm(m["matched"]) else "   <- different name"
        print(f"  {m['dish'][:38]:<38} {m['servings']:>4} -> {str(m['matched'])[:34]:<34} "
              f"{m['how']:<9}{flag}")
    print()

    if unmatched:
        print("=" * 72)
        print("NOT MATCHED - these are NOT in the order below. Fix the name or add the recipe:")
        for u in unmatched:
            print(f"  !! {u['dish']}  ({u['servings']} portions) - {u['why']}")
            for c in u.get("candidates", []):
                print(f"       closest in Apicbase: {c}")
        print("=" * 72 + "\n")

    if not matched:
        sys.exit("Nothing matched, so there is nothing to order.")

    detail = {}
    if args.recipes or spec.get("recipeDetail"):
        print("reading each matched recipe from Apicbase…")
        for m in matched:
            try:
                r = api(f"/products/recipes/{m['id']}/")
            except RuntimeError as e:
                print(f"  !! {m['matched']}: {e}")
                continue
            lines = r.get("ingredients") or r.get("recipe_lines") or r.get("lines") or []
            rows_ = []
            for ln in lines:
                ing = ln.get("ingredient") or ln.get("stock_item") or {}
                sub = ln.get("recipe") or ln.get("sub_recipe") or {}
                q = ln.get("quantity") or ln.get("amount") or {}
                rows_.append({
                    "name": ing.get("name") or sub.get("name") or ln.get("name") or "?",
                    "qty": q.get("value") if isinstance(q, dict) else q,
                    "unit": (q.get("unit") if isinstance(q, dict) else ln.get("unit")) or "",
                    "sub": bool(sub and not ing.get("name")),
                })
            detail[str(m["id"])] = {"name": r.get("name"), "servings": r.get("servings")
                                    or r.get("portions"), "lines": rows_}
            print(f"  {str(r.get('name'))[:46]:<46} {len(rows_)} lines")
        print()

    bom = api("/bom/recipes/", body={
        "outlet_id": outlet["id"],
        "recipes": [{"id": m["id"], "servings": m["servings"]} for m in matched],
        "consider_stock": False,              # Apicbase stock is not kept current
        "consider_outstanding_orders": False,
    })

    # The BOM's supplier_packages carry no article number - that lives on the
    # supplier_packages endpoint. Pull it once and join on the package id.
    print("fetching supplier article numbers…")
    art = {}
    for sp in pages("/products/supplier_packages/"):
        art[str(sp.get("id"))] = {
            "article": sp.get("supplier_article_number") or "",
            "product": sp.get("supplier_product_name") or "",
            "stockItem": (sp.get("stock_item") or {}).get("name") or "",
        }
    print(f"  {sum(1 for v in art.values() if v['article'])} of {len(art)} packages have an article number")

    rows = []
    for ing in bom.get("ingredients") or []:
        need = (ing.get("needed_quantity") or {})
        pack = next((p for p in (ing.get("supplier_packages") or [])
                     if str(p.get("id")) == str(ing.get("cheapest_package_id"))),
                    (ing.get("supplier_packages") or [None])[0])
        sup = (pack or {}).get("supplier") or {}
        extra = art.get(str((pack or {}).get("id")), {})
        rows.append({
            "name": ing.get("name") or "", "cat": ing.get("category") or "",
            "qty": need.get("value"), "unit": need.get("unit") or "",
            "supplier": sup.get("name") or "- no supplier -",
            "article": extra.get("article") or "",
            "supplierEmail": sup.get("email") or "",
            "order": (pack or {}).get("order_description") or (pack or {}).get("order_quantity") or "",
            "pack": (pack or {}).get("name") or "",
            "packProduct": extra.get("product") or extra.get("stockItem") or (pack or {}).get("name") or "",
            "price": (pack or {}).get("order_total_price"),
            "orderable": bool(ing.get("is_orderable")),
        })
    rows.sort(key=lambda r: (r["supplier"], r["name"]))

    print(f"ORDER - {len(rows)} ingredients, "
          f"{sum(1 for r in rows if r['article'])} with an article number, stock NOT subtracted")
    print("-" * 72)
    sup = None
    for r in rows:
        if r["supplier"] != sup:
            sup = r["supplier"]
            print(f"\n## {sup}")
        art = f"[{r['article']}] " if r["article"] else ""
        line = f"  {r['name'][:40]:<40} {str(r['qty'])[:10]:>10} {r['unit']:<6} {art}{r['order']}"
        if args.prices and r["price"] is not None:
            line += f"  EUR {r['price']}"
        if not r["orderable"]:
            line += "   (not orderable)"
        print(line)

    prep = bom.get("stockable_recipes") or []
    if prep:
        print(f"\n\nPREPARE IN THE KITCHEN - {len(prep)} sub-recipes (not bought)")
        print("-" * 72)
        for p in prep:
            q = (p.get("needed_quantity") or {})
            print(f"  {(p.get('ingredient') or {}).get('name','')[:50]:<50} "
                  f"{str(q.get('value'))[:10]:>10} {q.get('unit') or ''}")
    if args.firebase:
        token = fb_token()
        key = re.sub(r"[^A-Za-z0-9_-]", "-", spec.get("week") or "order")
        fb_put(f"apicbase/orders/{key}", {
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "week": spec.get("week"), "range": spec.get("range"),
            "kitchen": spec.get("kitchen"), "outlet": outlet.get("name"),
            "events": spec.get("events"),
            "dishes": len(demand), "portions": sum(d["servings"] for d in demand),
            "matched": [{"dish": m["dish"], "servings": m["servings"],
                         "apicbase": m["matched"], "how": m["how"]} for m in matched],
            "unmatched": unmatched, "rows": rows, "recipes": detail,
            "prepare": [{"name": (p.get("ingredient") or {}).get("name", ""),
                         "qty": (p.get("needed_quantity") or {}).get("value"),
                         "unit": (p.get("needed_quantity") or {}).get("unit")} for p in prep],
        }, token)
        fb_put("apicbase/orders/latest", key, token)
        print(f"\nWritten to Firebase: apicbase/orders/{key}")

    print(f"\nDone. {len(unmatched)} dish(es) not matched.")


if __name__ == "__main__":
    main()
