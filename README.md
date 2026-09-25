# NRW Stock Planner

Live: https://berlinkitchen123-blip.github.io/Inventory/ (repo `berlinkitchen123-blip/Inventory`)

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
- **Team data:** everything people type is saved online in Firebase (project `stock-f24`) and shared live.
  Sign in with a @bellabona.com email.

## Files

| File | What it does |
|---|---|
| `index.html` | The tool. Loads the two data files below, and the team data from Firebase. |
| `data/db-snapshot.json` | NRW menus (2 weeks back to 8 weeks ahead) and their recipes. GitHub refreshes it every hour. |
| `data/kitchen-settings.json` | NRW defaults: suppliers, pack sizes, yields, buffer, first delivery, checks, Firebase web settings. |
| `database.rules.json` | Firebase security rules: only verified @bellabona.com accounts can read or change the team data. |
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

## Team data (Firebase)

Forecasts, stock counts, suppliers, pack sizes, yields and the buffer are saved in the Firebase Realtime Database
of project `stock-f24`, under `nrw-stock-planner/`. Everyone signed in sees the same numbers, live. Nothing is
written to the BB database or Apicbase. The Firebase web settings in `data/kitchen-settings.json` are not a
secret; the database rules protect the data.

One-time setup at console.firebase.google.com, project stock-f24:

1. *Build > Authentication > Get started > Sign-in method > Email/Password*: Enable, Save.
2. *Authentication > Settings > Authorized domains > Add domain*: `berlinkitchen123-blip.github.io`.
3. *Build > Realtime Database > Rules*: paste `database.rules.json`, Publish.
   If other tools use this database, add only the `"nrw-stock-planner": { ... }` block inside the existing
   rules. Make sure no rule at the top gives `.read` or `.write` to everyone (test mode does: it shows `now <`).
4. Open the planner, type your @bellabona.com email and a password, *Create account*, click the link in the
   email, *Continue*. Each team member does the same.

Backup: *Realtime Database > Data > ⋮ > Export JSON*.
