"""Refresh data/db-snapshot.json for the NRW Stock Planner from the BB database (read-only).

NRW only: menus of the NRW kitchen or with "NRW" in the name, by date (2 weeks back to 8 weeks ahead), every dish type, with recipes.
Runs every hour in GitHub Actions (.github/workflows/refresh-data.yml), or locally:
    DB_HOST=... DB_USER=... DB_PASSWORD=... DB_NAME=... python scripts/export_data.py
Optional: DB_PORT (3306), DB_SSL=1, NRW_KITCHEN_ID
"""
import datetime as dt
import json
import os
import pathlib
import ssl

import pymysql

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "db-snapshot.json"
KITCHEN = os.getenv("NRW_KITCHEN_ID") or "7db45333-aa9e-11f1-bb08-02be5bcdbea3"  # NRW Remscheid
UNITS = {"kg": (1000, "g"), "g": (1, "g"), "gr": (1, "g"), "l": (1000, "ml"), "ml": (1, "ml"),
         "ea": (1, "pcs"), "piece": (1, "pcs"), "pcs": (1, "pcs")}

# NRW menus that touch the window: linked to the NRW kitchen, or "NRW" in the name
# (the NRW menus in the admin are not linked to a kitchen yet).
MENUS_SQL = """
SELECT DISTINCT m.id, m.name, m.startDate, m.endDate
FROM menu_v2 m LEFT JOIN menu_v2_kitchens_kitchen mk ON mk.menuV2Id = m.id
WHERE (mk.kitchenId = %s OR m.name LIKE '%%NRW%%') AND m.isActive = 1 AND m.deletedAt IS NULL
  AND m.endDate >= %s AND m.startDate <= %s
ORDER BY m.startDate
"""

MENU_DISHES_SQL = """
SELECT rv.id, rv.cat, rv.variantName, rv.portion
FROM menu_v2_dishes_recipe_variants md JOIN recipe_variants rv ON rv.id = md.recipeVariantsId
WHERE md.menuV2Id = %s
ORDER BY rv.cat, rv.variantName
"""

# Recipe lines of dishes or sub-recipes. portion of a sub-recipe = its yield in grams.
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


def main():
    if not os.getenv("DB_HOST"):
        print("DB secrets are not set yet. Keeping the current data file.")
        return
    today = dt.date.today()
    conn = pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.getenv("DB_PORT") or 3306),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"], database=os.environ["DB_NAME"],
        ssl=ssl.create_default_context() if os.getenv("DB_SSL") == "1" else None,
        cursorclass=pymysql.cursors.DictCursor, read_timeout=120)
    with conn, conn.cursor() as cur:
        cur.execute(MENUS_SQL, (KITCHEN, today - dt.timedelta(days=14), today + dt.timedelta(days=56)))
        menus, dishes = [], {}
        for m in cur.fetchall():
            cur.execute(MENU_DISHES_SQL, (m["id"],))
            ids = []
            for r in cur.fetchall():
                dishes[r["id"]] = {"name": r["variantName"], "type": r["cat"], "portion": num(r["portion"])}
                ids.append(r["id"])
            if ids:
                menus.append({"id": m["id"], "name": m["name"], "from": str(m["startDate"])[:10],
                              "to": str(m["endDate"])[:10], "dishes": ids})
        wanted = set(dishes)
        lines, subs, sub_names, ingredients, warnings = {i: [] for i in wanted}, {}, {}, {}, set()
        frontier, depth = sorted(wanted), 0
        while frontier and depth < 6:  # depth 0 = dish lines, 1+ = sub-recipe lines
            cur.execute(LINES_SQL.format(ph=",".join(["%s"] * len(frontier))), frontier)
            new_subs = []
            for r in cur.fetchall():
                qty, unit = base(r["amount"], r["unit"])
                sid = r["subRecipeId"]
                if sid:
                    if sid not in sub_names:
                        name = r["sub_name"] or sid
                        sub_names[sid] = name if name not in subs else f"{name} [{sid[:8]}]"
                        subs[sub_names[sid]] = {"dbYield": num(r["sub_yield"]) or None, "input": 0, "lines": []}
                        new_subs.append(sid)
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
                if depth == 0:
                    lines[r["owner"]].append([item, kind, qty, unit])
                else:
                    subs[sub_names[r["owner"]]]["lines"].append([item, qty, unit, kind])
            frontier, depth = new_subs, depth + 1
    for s in subs.values():
        s["input"] = num(sum(q for _, q, u, _ in s["lines"] if u in ("g", "ml")))
    payload = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
               "kitchen": "NRW",
               "menus": menus, "dishes": dishes, "lines": lines, "subs": subs,
               "ingredients": ingredients, "warnings": sorted(warnings)}
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    if {k: v for k, v in old.items() if k != "generated"} == {k: v for k, v in payload.items() if k != "generated"}:
        print("No changes in the database data.")
        return
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"Wrote {OUT.name}: {len(menus)} menu(s), {len(dishes)} dishes, {len(subs)} sub-recipes.")


if __name__ == "__main__":
    main()
