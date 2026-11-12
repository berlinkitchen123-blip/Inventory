"""Check the Apicbase API token and endpoints before any real sync runs.

Prints counts and field names only - never recipe names, suppliers or prices, because the
Actions log of a public repository is public.

    APICBASE_TOKEN=... python scripts/apicbase_probe.py
Optional: APICBASE_BASE (default https://api.apicbase.com/api/v2)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = (os.getenv("APICBASE_BASE") or "https://api.apicbase.com/api/v2").rstrip("/")
TOKEN = os.getenv("APICBASE_TOKEN") or ""

# Endpoints the sync will depend on. (label, path, params)
CHECKS = [
    ("outlets",           "/accounts/outlets/",           {}),
    ("recipes",           "/products/recipes/",           {"page_size": 1}),
    ("ingredients",       "/products/ingredients/",       {"page_size": 1}),
    ("stock items",       "/products/stock_items/",       {"page_size": 1}),
    ("supplier packages", "/products/supplier_packages/", {"page_size": 1}),
    ("menus",             "/products/menus/",             {"page_size": 1}),
]


def get(path, params=None):
    """One GET. Returns (status, payload, headers). Never raises on an HTTP error."""
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "User-Agent": "bellabona-nrw-planner/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return e.code, {"error": body}, dict(e.headers or {})
    except Exception as e:  # network, timeout, bad JSON
        return 0, {"error": f"{type(e).__name__}: {e}"}, {}


def shape(payload):
    """Describe a list response without printing any values."""
    if not isinstance(payload, dict):
        return f"not an object ({type(payload).__name__})"
    count = payload.get("count")
    results = payload.get("results")
    if not isinstance(results, list):
        return f"no results[]; keys = {sorted(payload)[:12]}"
    fields = sorted(results[0]) if results else []
    return f"count={count}, fields={fields}"


def main():
    if not TOKEN:
        sys.exit("APICBASE_TOKEN is not set. Add it as a repository secret.")
    print(f"base = {BASE}")
    print(f"token = {len(TOKEN)} characters, starts '{TOKEN[:3]}...'\n")

    ok, failed = 0, []
    for label, path, params in CHECKS:
        status, payload, headers = get(path, params)
        left = headers.get("X-RateLimit-Remaining", "?")
        if status == 200:
            ok += 1
            print(f"  OK   {label:18} {path:32} {shape(payload)}  [rate left {left}]")
        else:
            failed.append((label, path, status))
            note = payload.get("error", "")[:120] if isinstance(payload, dict) else ""
            print(f"  FAIL {label:18} {path:32} HTTP {status}  {note}")
        time.sleep(0.7)  # stay well under 100 requests a minute

    # The BOM endpoint needs the procurement scope; a 400 here still proves the scope is granted.
    print()
    status, payload, _ = get("/bom/recipes/")
    if status in (400, 405):
        print(f"  OK   bom scope        /bom/recipes/   reachable (HTTP {status} = needs a POST body, as expected)")
    elif status == 403:
        print("  FAIL bom scope        /bom/recipes/   HTTP 403 - the token is missing the 'procurement' scope")
        failed.append(("bom scope", "/bom/recipes/", 403))
    else:
        print(f"  ?    bom scope        /bom/recipes/   HTTP {status}")

    # How a menu points at its dishes. The sync reads menu -> recipe ids from this,
    # and the planner showed menus with no dishes, so the shape has to be checked.
    print()
    status, payload, _ = get("/products/menus/", {"page_size": 10})
    if status == 200:
        rows = payload.get("results") or []
        print(f"  menu fields = {sorted(rows[0]) if rows else 'none'}")
        for m in rows:
            c = m.get("courses")
            if isinstance(c, list) and c:
                first = c[0]
                if isinstance(first, dict):
                    print(f"  courses = list of objects, keys = {sorted(first)}")
                    for k, v in first.items():          # shape only, never a value
                        kind = type(v).__name__
                        if isinstance(v, str):
                            kind += " url" if v.startswith("http") else " text"
                        elif isinstance(v, list) and v:
                            kind += f" of {type(v[0]).__name__}"
                            if isinstance(v[0], dict):
                                kind += f" keys={sorted(v[0])}"
                            elif isinstance(v[0], str):
                                kind += " url" if v[0].startswith("http") else " text"
                        print(f"      {k:22} {kind}")
                else:
                    print(f"  courses = list of {type(first).__name__}, "
                          f"url={str(first).startswith('http')}")
                break
        else:
            print("  none of the first 10 menus has any courses")

    print(f"\n{ok}/{len(CHECKS)} endpoints reachable.")
    if failed:
        print("Failed: " + ", ".join(f"{l} ({s})" for l, _, s in failed))
        print("\n401/403 = token or scope problem. 404 = the path differs on this account;")
        print("send me the line above and I will correct it.")
        sys.exit(1)
    print("All good - the full sync can run.")


if __name__ == "__main__":
    main()
