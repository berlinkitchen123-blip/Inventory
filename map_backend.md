# map_backend
BB database (MySQL replica, read-only), NRW only
├── menu_v2 (LEFT JOIN menu_v2_kitchens_kitchen) where kitchen = NRW 7db45333-… OR name LIKE '%NRW%'
│   (the admin's NRW menus have no kitchen linked) ─ menu_v2_dishes_recipe_variants -> menus, today-14d .. +56d, all dish types
├── recipe_variants_ingredients_recipe_ingredient ─ recipe_ingredient -> recipe lines (net qty)
├── recipe_variants.portion -> dish weight | sub-recipe yield (g)
└── ingredients_v2 (name, type, apicCategory)
   (forecasts table has no quantities -> forecast is typed in the tool)
        │
scripts/export_data.py  <- .github/workflows/refresh-data.yml (hourly at :07, secrets DB_*)
        -> data/db-snapshot.json
           {generated, kitchen:"NRW", menus[{id,name,from,to,dishes[]}], dishes{id:{name,type,portion}},
            lines{id:[[name,I|S,qty,unit]]}, subs{name:{dbYield,input,lines[[name,qty,unit,I|S]]}},
            ingredients{name:{type,cat}}, warnings[]}
Apicbase (stock list filtered per supplier; pulled once, 24 Sep 2026)
        -> data/kitchen-settings.json: suppliers{item:supplier}, supplierOptions{item:[..]}, supplierList[],
           packs{item:size}, packInfo{item:stock item name}
data/kitchen-settings.json (also: kitchen, firstDelivery, buffer, yields{name:{yield,why,confirmed}}, units{}, groups{},
        notes{}, checks[], optional forecast{day:{dishId:portions}} from "Download settings file")
index.html
├── fetch data/*.json (no-store) -> fallback embedded #seedDb / #seedSettings
└── localStorage "nrw-stock-planner-v1" -> ST {fc{day:{dish:n}}, stock{week:{item:n}}, suppliers, packs, yields, buffer, showDishes, view}
