# map_frontend
index.html
├── header ── #kitchen ── #freshness (data date, built-in copy?)
├── .weekbar ── [data-step ±7] -> WEEK (not saved; defaultWeek(): next week with an NRW menu and a delivery to come, or ?week=YYYY-MM-DD)
│   ├── #week ticket: week no, dates, deliveryLabel(deliveriesFor(WEEK)), forecast total, NRW menu name(s)
│   │   └── FIRST_WEEK = firstServiceWeek(): first week with an NRW menu -> gets Delivery 1
│   └── #weeks chips [data-goto] ── 8 weeks, menu yes/no, portions typed
├── details.settings ── buffer% -> ST.buffer
├── tabs [data-tab] -> ST.view
│   ├── Menu & forecast -> renderForecast() ── grid dish x Mon..Fri (– = not on that day's menu; tag if recipe < half the dish weight)
│   │   ├── [data-fc "day|dishId"] -> ST.fc[day][dishId] ── [data-fill dishId] -> all menu days of the dish
│   │   └── #clearWeek -> delete ST.fc[days of week]
│   ├── Order list -> renderOrder() ── bySupplier() ── itemHtml()
│   │   ├── per supplier: Item | Dish | Portions | Need | Stock | To order | Pack size | Packs
│   │   ├── [data-sup] -> ST.suppliers ── [data-stock] -> ST.stock[weekKey] ── [data-pack] -> ST.packs
│   │   ├── #search (item or dish) ── #showDishes -> ST.showDishes
│   │   ├── #xlsxBtn -> exportExcel() (SheetJS from cdnjs, loaded on click) sheets: Order (Name, Qty, Unit), By supplier and dish
│   │   └── #printBtn -> window.print() (@media print)
│   ├── Yields -> renderYields() ── [data-yield] / [data-confirm] -> ST.yields ── #settingsBtn -> exportSettings()
│   └── Checks -> renderChecks() ── SET.checks + DB.warnings ── #clearAll -> ST reset
├── startup: load data -> FIRST_WEEK -> WEEK -> tidyOldData() (old tab names, old flat stock -> this week, old keys removed)
├── window 'error' -> #appError (readable message instead of a silent crash)
└── core (pure, no DOM) /*CORE-START*/ … /*CORE-END*/
    ├── weekMenu(DB, days) -> NRW menus of the week, dishes per day (onDay), dish ids sorted by type
    ├── computePlan(DB, SET, ST, week) -> {dishes[perDay, portions], rows[{item, supplier, dishes[], need, stock, toOrder, packs}], subs[]}
    ├── yieldInfo(): ST.yields > SET.yields > DB dbYield > batch input
    └── ruleGroup(): group for items missing in SET.groups (Fresh tag)
