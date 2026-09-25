# NRW Stock Planner

Shows what the NRW kitchen (Remscheid) has to order, week by week. Delivery 1 is Tue 29 Sep 2026, then every Friday
for the next week. NRW data only.

- **Weeks:** move with ‹ › or the week chips. Each week shows its NRW menu from the BB database, by date. An NRW menu
  is a menu of the NRW kitchen, or one with "NRW" in its name (e.g. "5.10 to 9.10 Oct 26 NRW"). A week without one
  stays empty until the menu team adds it. Delivery 1 (Tue 29 Sep) counts for the first week that has an NRW menu.
- **Menu & forecast:** every dish on that week's menu, day by day. You type the portions per dish and day.
  *All days* puts the same number on every day. Dishes whose recipe in the DB looks incomplete are flagged.
- **Order list:** one block per item (e.g. rice) with every dish that uses it, that dish's portions for the week and
  how much of the item it needs, then stock on hand, what to order and packs. Grouped by supplier.
- **Download Excel:** sheet *Order* = Name, Qty (to order), Unit. Sheet *By supplier and dish* = the full breakdown.
- **Suppliers and pack sizes:** Apicbase defaults until the NRW outlet is set up there. Change the supplier on any item.

## Files

| File | What it does |
|---|---|
| `index.html` | The tool. Works on its own (even offline) with a built-in copy of the data. |
| `data/db-snapshot.json` | NRW menus (2 weeks back to 8 weeks ahead) and their recipes. GitHub refreshes it every hour. |
| `data/kitchen-settings.json` | NRW settings: suppliers, pack sizes, yields, buffer, first delivery, checks. |
| `scripts/export_data.py` | Reads the BB database (read-only) and writes `db-snapshot.json`. |
| `.github/workflows/refresh-data.yml` | Runs the export every hour. |
| `docs/` | Code maps. |

## Put it on GitHub

1. Create a new **private** repository, for example `nrw-stock-planner`.
2. Unzip and drag all files and folders into *Add file > Upload files*. If the `.github` folder is skipped
   (hidden folders often are), use *Add file > Create new file*, name it `.github/workflows/refresh-data.yml`
   and paste the file content.
3. *Settings > Pages*: Deploy from a branch, `main`, `/ (root)`, Save. The tool is then at
   `https://<account>.github.io/nrw-stock-planner/`. Add `?week=2026-10-05` to open a given week.

**Privacy:** GitHub Pages sites are public, even from a private repository, unless the GitHub plan has
private Pages (Enterprise). The data contains recipes, so check with the tech team first, or host it behind a
login (Cloudflare Pages + Cloudflare Access).

## Hourly refresh from the BB database

*Settings > Secrets and variables > Actions > New repository secret*, add `DB_HOST`, `DB_PORT`, `DB_USER`,
`DB_PASSWORD`, `DB_NAME` (and `DB_SSL` = `1` if the database needs SSL). Use a **read-only** login from the
tech team, and ask them to allow GitHub to connect. Test it with *Actions > Refresh data from BB database >
Run workflow*. Until the secrets exist, the workflow skips and the tool keeps the data from 24 Sep 2026.

## Every week

1. Pick the week. Check the NRW menu.
2. *Menu & forecast*: type the portions per dish and day.
3. *Order list*: type the stock you counted. Order what *To order* and *Packs* say, supplier by supplier.
4. *Download Excel* or *Print order*.

## Sharing with the team

Forecasts, stock, suppliers, pack sizes and yields are saved in that browser only. To share them:
*Yields > Download settings file*, then upload it to the `data` folder in the repo (replace the old file).
