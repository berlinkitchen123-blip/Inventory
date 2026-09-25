# map_frontend
index.html
├── header ── #kitchen ── #freshness ── #status (online/offline, last change) ── #userEmail ── #signOut
├── #auth (hidden when signed in) ── #authForm submit -> STORE.signIn ── #aSignup -> STORE.signUp (+ verification mail)
│   ├── #aReset -> STORE.reset ── #verifyBox: #vContinue -> STORE.refresh -> onAuth ── #vResend
│   └── creds(): email must end with @SET.allowedEmailDomain
├── #app (shown when signed in + email verified)
├── .weekbar ── [data-step ±7] -> WEEK (not saved; defaultWeek(): next week with an NRW menu and a delivery to come, or ?week=YYYY-MM-DD)
│   ├── #week ticket: week no, dates, deliveryLabel(deliveriesFor(WEEK)), forecast total, NRW menu name(s)
│   │   └── FIRST_WEEK = firstServiceWeek(): first week with an NRW menu -> gets Delivery 1
│   └── #weeks chips [data-goto] ── 8 weeks, menu yes/no, portions typed
├── details.settings ── buffer% -> settings/buffer
├── tabs [data-tab] -> ST.view
│   ├── Menu & forecast -> renderForecast() ── grid dish x Mon..Fri (– = not on that day's menu; tag if recipe < half the dish weight)
│   │   ├── [data-fc "day|dishId"] -> forecast/{day}/{dishId} ── [data-fill dishId] -> all menu days of the dish
│   │   └── #clearWeek -> forecast/{day} = null for the 5 days (whole team)
│   ├── Order list -> renderOrder() ── bySupplier() ── itemHtml()
│   │   ├── per supplier: Item | Dish | Portions | Need | Stock | To order | Pack size | Packs
│   │   ├── [data-sup] -> suppliers/{item} ── [data-stock] -> stock/{monday}/{item} ── [data-pack] -> packs/{item}
│   │   ├── #stockEditBtn -> STOCK_EDIT: stock is text until Edit stock; Done, week change or tab change locks it
│   │   ├── #search (item or dish) ── #showDishes -> ST.showDishes
│   │   ├── #xlsxBtn -> exportExcel() (SheetJS from cdnjs, loaded on click) sheets: Order (Name, Qty, Unit), By supplier and dish
│   │   └── #printBtn -> window.print() (@media print)
│   ├── Yields -> renderYields() ── [data-yield] / [data-confirm] -> yields/{sub}
│   └── Checks -> renderChecks() ── SET.checks + incomplete recipes + DB.warnings
├── startup: load data -> FIRST_WEEK -> WEEK -> cacheLoad() -> STORE (Firebase, or window.__STORE__ in tests) -> onAuth
├── onAuth(user): listen(nrw-stock-planner) -> applyRemote() -> ST.{fc, stock, suppliers, packs, yields, buffer}, LAST
│   ├── cacheSave() (localStorage copy, removed on sign-out) ── migrateOld() once (old browser numbers -> upload?)
│   └── renderFromRemote(): waits while a field is being typed, then rerenderSoon()
├── every edit -> put({path: value}) -> STORE.update (one multi-path write + meta/lastChange {by, at, what})
├── window 'error' -> #appError (readable message instead of a silent crash)
├── 'wheel' on a focused number field -> blur (scrolling never changes a number)
└── core (pure, no DOM) /*CORE-START*/ … /*CORE-END*/
    ├── weekMenu(DB, days) -> NRW menus of the week, dishes per day (onDay), dish ids sorted by type
    ├── computePlan(DB, SET, ST, week) -> {dishes[perDay, portions], rows[{item, supplier, dishes[], need, stock, toOrder, packs}], subs[]}
    ├── yieldInfo(): ST.yields > SET.yields > DB dbYield > batch input
    └── ruleGroup(): group for items missing in SET.groups (Fresh tag)
