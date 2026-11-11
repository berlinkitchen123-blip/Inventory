"""Find the real Apicbase recipe behind a dish name, and read what is in it.

    APICBASE_TOKEN=... python scripts/dishes.py --find couscous caesar falafel
    APICBASE_TOKEN=... python scripts/dishes.py --detail 123456 789012
    APICBASE_TOKEN=... python scripts/dishes.py --unmatched data/catering-demand.json

--find      every recipe whose name contains any of the words given, with its id.
--detail    one recipe's ingredient lines as Apicbase holds them: real ingredient
            name, quantity per the recipe's own yield, and the supplier behind it.
--unmatched take the dish names from a demand file and search for each of them.

Nothing here guesses. It prints candidates for a human to choose from; the
chosen id goes into data/dish-map.json, which is what bom.py actually uses.
"""
import argparse
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
PAGE, GAP = 200, 0.7
_last = [0.0]


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


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


STOP = {"with", "and", "the", "a", "of", "in", "on", "for", "halves", "portions",
        "mini", "style", "bite", "bites", "cup", "cups", "salad", "sandwich"}


def find(recipes, terms, limit=12):
    """Every recipe containing any of the words, best overlap first."""
    want = [norm(t) for t in terms if norm(t)]
    scored = []
    for r in recipes:
        key = norm(r.get("name"))
        if not key or key.endswith(" ct"):          # never the "- CT" copies
            continue
        hit = sum(1 for w in want if w and w in key)
        if hit:
            scored.append((hit, -len(key), r))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [r for _, _, r in scored[:limit]]


def show_detail(rid):
    r = api(f"/products/recipes/{rid}/")
    name = r.get("name") or ""
    yield_q = r.get("yield") or r.get("yield_quantity") or {}
    print(f"\n{'=' * 72}\n{name}   (id {rid})")
    print(f"  yield: {json.dumps(yield_q) if isinstance(yield_q, dict) else yield_q}"
          f"   servings: {r.get('servings') or r.get('portions') or '?'}")
    lines = r.get("ingredients") or r.get("recipe_lines") or r.get("lines") or []
    if not lines:
        print(f"  no ingredient lines on this recipe. keys: {sorted(r.keys())}")
        return
    print(f"  {len(lines)} lines")
    for ln in lines:
        ing = ln.get("ingredient") or ln.get("stock_item") or {}
        sub = ln.get("recipe") or ln.get("sub_recipe") or {}
        q = ln.get("quantity") or ln.get("amount") or {}
        qty = q.get("value") if isinstance(q, dict) else q
        unit = (q.get("unit") if isinstance(q, dict) else ln.get("unit")) or ""
        what = ing.get("name") or sub.get("name") or ln.get("name") or "?"
        kind = "sub-recipe" if (sub and not ing.get("name")) else "ingredient"
        sup = ""
        for p in (ing.get("supplier_packages") or []):
            s = (p.get("supplier") or {}).get("name")
            if s:
                sup = f"   <- {s}"
                if p.get("supplier_article_number"):
                    sup += f" [{p['supplier_article_number']}]"
                break
        print(f"    {what[:46]:<46} {str(qty)[:9]:>9} {unit:<5} {kind:<10}{sup}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", nargs="*", default=[])
    ap.add_argument("--detail", nargs="*", default=[])
    ap.add_argument("--unmatched", help="a demand file: search for every dish in it")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()
    if not os.getenv("APICBASE_TOKEN"):
        sys.exit("APICBASE_TOKEN is not set.")

    for rid in args.detail:
        show_detail(rid)

    terms, dishes = list(args.find), []
    if args.unmatched:
        spec = json.load(open(args.unmatched, encoding="utf-8"))
        dishes = [d["dish"] for d in spec["demand"]]

    if not terms and not dishes:
        return

    recipes = pages("/products/recipes/")
    print(f"\nrecipes in library: {len(recipes)}")
    by_norm = {}
    for r in recipes:
        by_norm.setdefault(norm(r.get("name")), []).append(r)

    if terms:
        print(f"\n{'=' * 72}\nCANDIDATES for: {', '.join(terms)}")
        for r in find(recipes, terms, args.limit):
            print(f"  {r['id']}  {r.get('name')}")

    for dish in dishes:
        key = norm(dish)
        if by_norm.get(key):
            hit = by_norm[key][0]
            print(f"\nOK  {dish}\n      -> {hit['id']}  {hit.get('name')}")
            continue
        words = [w for w in key.split() if w not in STOP and len(w) > 2]
        cands = find(recipes, words, args.limit)
        print(f"\n??  {dish}")
        if not cands:
            print("      nothing in the library contains any of its words")
        for r in cands:
            print(f"      {r['id']}  {r.get('name')}")


if __name__ == "__main__":
    main()
