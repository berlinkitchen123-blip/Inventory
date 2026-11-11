"""Refresh data/dish-catalog.json for the Order Calculator from the BB database (read-only).

Every active dish with a recipe, not just the ones on an NRW menu, so catering dishes can be
costed too. Sub-recipes are followed to raw ingredients, same as export_data.py.
Dishes whose name ends in "- CT" are left out: they are not used.

Runs every hour in GitHub Actions (.github/workflows/refresh-data.yml), or locally:
    DB_HOST=... DB_USER=... DB_PASSWORD=... DB_NAME=... python scripts/export_dishes.py
Optional: DB_PORT (3306), DB_SSL=1
"""
import datetime as dt
import json
import os
import pathlib
import ssl

import pymysql

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "dish-catalog.json"
UNITS = {"kg": (1000, "g"), "g": (1, "g"), "gr": (1, "g"), "l": (1000, "ml"), "ml": (1, "ml"),
         "ea": (1, "pcs"), "piece": (1, "pcs"), "pcs": (1, "pcs")}
CHUNK = 400  # ids per IN (...) query

DISHES_SQL = """
SELECT rv.id, rv.variantName, rv.cat, rv.portion, rv.apicbaseId
FROM recipe_variants rv
WHERE rv.deletedAt IS NULL AND rv.isActive = 1
  AND rv.variantName IS NOT NULL AND rv.variantName <> ''
  AND rv.variantName NOT LIKE '%%- CT'
  AND rv.variantName NOT LIKE '%%- CT %%'
  AND rv.variantName NOT LIKE '%% CT'
ORDER BY rv.variantName
"""

LINES_SQL = """
SELECT x.recipeVariantsId AS owner, ri.name AS line_name, ri.amount, ri.unit, ri.ingredientId, ri.subRecipeId,
       i.name AS ing_name, i.type AS ing_type, i.apicCategory AS ing_cat,
       sr.variantName AS sub_name, sr.portion AS sub_yield
FROM recipe_variants_ingredients_recipe_ingredient x
JOIN recipe_ingredient ri ON ri.id = x.recipeIngredientId AND ri.deletedAt IS NULL
LEFT JOIN ingredients_v2 i ON i.id = ri.ingredientId
LEFT JOIN recipe_variants sr ON sr.id = ri.subRecipeId
WHERE x.recipeVariantsId IN ({ph})
ORDER BY x.recipeVariantsId, ri.name
"""


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 3)


def base(amount, unit):
    u = (unit or "").strip().lower()
    factor, unit_out = UNITS.get(u, (1, u or "g"))
    return num(float(amount or 0) * factor), unit_out


def fetch_lines(cur, ids):
    """All recipe lines of these ids, in chunks the database is happy with."""
    out = []
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        cur.execute(LINES_SQL.format(ph=",".join(["%s"] * len(part))), part)
        out.extend(cur.fetchall())
    return out


def main():
    if not os.getenv("DB_HOST"):
        print("DB secrets are not set yet. Keeping the current data file.")
        return
    conn = pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.getenv("DB_PORT") or 3306),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"], database=os.environ["DB_NAME"],
        ssl=ssl.create_default_context() if os.getenv("DB_SSL") == "1" else None,
        cursorclass=pymysql.cursors.DictCursor, read_timeout=180)
    with conn, conn.cursor() as cur:
        cur.execute(DISHES_SQL)
        dishes = {r["id"]: {"name": r["variantName"], "type": r["cat"], "portion": num(r["portion"]),
                            "apic": r["apicbaseId"] or None} for r in cur.fetchall()}
        lines, subs, sub_names, ingredients, warnings = {i: [] for i in dishes}, {}, {}, {}, set()
        seen = {i: set() for i in dishes}          # drop the duplicate line rows the join can produce
        frontier, depth = sorted(dishes), 0
        while frontier and depth < 6:              # depth 0 = dish lines, 1+ = sub-recipe lines
            new_subs = []
            for r in fetch_lines(cur, frontier):
                qty, unit = base(r["amount"], r["unit"])
                sid = r["subRecipeId"]
                if sid:
                    if sid not in sub_names:
                        name = r["sub_name"] or sid
                        sub_names[sid] = name if name not in subs else f"{name} [{sid[:8]}]"
                        subs[sub_names[sid]] = {"dbYield": num(r["sub_yield"]) or None, "input": 0, "lines": []}
                        new_subs.append(sid)
                        seen[sid] = set()
                    item, kind = sub_names[sid], "S"
                elif r["ingredientId"] and r["ing_name"]:
                    item, kind = r["ing_name"], "I"
                    ingredients[item] = {"type": r["ing_type"], "cat": r["ing_cat"]}
                elif "water" in (r["line_name"] or "").lower():
                    item, kind = "Water", "I"
                else:
                    owner = dishes[r["owner"]]["name"] if depth == 0 else sub_names.get(r["owner"], r["owner"])
                    warnings.add(f"{owner}: line '{r['line_name']}' has no ingredient linked, skipped.")
                    continue
                key = (item, kind, qty, unit)
                if key in seen.setdefault(r["owner"], set()):
                    continue
                seen[r["owner"]].add(key)
                if depth == 0:
                    lines[r["owner"]].append([item, kind, qty, unit])
                else:
                    subs[sub_names[r["owner"]]]["lines"].append([item, qty, unit, kind])
            frontier, depth = new_subs, depth + 1
    for s in subs.values():
        s["input"] = num(sum(q for _, q, u, _ in s["lines"] if u in ("g", "ml")))
    empty = [i for i, v in lines.items() if not v]
    for i in empty:                                 # a dish with no recipe cannot be ordered against
        dishes.pop(i), lines.pop(i)
    payload = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
               "scope": "all active dishes with a recipe, excluding '- CT'",
               "dishes": dishes, "lines": lines, "subs": subs,
               "ingredients": ingredients, "warnings": sorted(warnings)}
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "generated"} == {k: v for k, v in payload.items() if k != "generated"}:
        print("No changes in the database data.")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"Wrote {OUT.name}: {len(dishes)} dishes, {len(subs)} sub-recipes, "
          f"{len(ingredients)} ingredients, {len(empty)} dishes without a recipe skipped.")


if __name__ == "__main__":
    main()
