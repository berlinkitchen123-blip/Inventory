"""Confirmed catering events out of Notion, for the planner to read.

Imported by sync_apicbase.py. Does nothing unless NOTION_TOKEN is set, so the
daily sync keeps working untouched until the token exists.

What it is for: the number of people comes from Notion, the portion size comes
from Apicbase. Matching an Apicbase menu to its Notion event therefore gives the
portions for every dish on that menu.

Set up once:
  1. Notion -> Settings -> Connections -> Develop or manage integrations ->
     New internal integration, scoped to this workspace, read content only.
  2. Open the Catering Tracking database -> ... -> Connections -> add it.
  3. Put the secret in the repository as NOTION_TOKEN and pass it to the sync job.
"""
import json
import os
import urllib.error
import urllib.request

DB = os.getenv("NOTION_DB") or "296a770a-e71a-801b-a008-c5a6fd76395c"
DS = os.getenv("NOTION_DS") or "296a770a-e71a-8017-bdf1-000b0f61c85b"
KEEP = {"Confirmed", "Delivered", "Invoiced", "ALL DONE"}    # everything already won


def _post(path, body, version):
    req = urllib.request.Request(
        "https://api.notion.com/v1" + path,
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
                 "Notion-Version": version, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def query(cursor=None):
    """One page of rows, from whichever endpoint this workspace answers on."""
    body = {"page_size": 100}
    if cursor:
        body["start_cursor"] = cursor
    try:
        return _post(f"/data_sources/{DS}/query", body, "2025-09-03")
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            raise
        return _post(f"/databases/{DB}/query", body, "2022-06-28")


def plain(prop):
    """A Notion property down to something plain."""
    if not isinstance(prop, dict):
        return None
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t) or []).strip()
    if t == "number":
        return prop.get("number")
    if t in ("select", "status"):
        return (prop.get(t) or {}).get("name")
    if t == "multi_select":
        return [x.get("name") for x in prop.get(t) or []]
    if t == "date":
        return (prop.get("date") or {}).get("start")
    if t == "checkbox":
        return bool(prop.get("checkbox"))
    return None


def events(since=None):
    """{event id: row} for confirmed events, newest dates last."""
    out, cursor = {}, None
    while True:
        page = query(cursor)
        for row in page.get("results") or []:
            p = row.get("properties") or {}
            status = plain(p.get("Status"))
            date = (plain(p.get("Event Date")) or "")[:10]
            if status not in KEEP or not date:
                continue
            if since and date < since:
                continue
            out[row["id"].replace("-", "")] = {
                "client": plain(p.get("Client")) or "",
                "date": date,
                "people": plain(p.get("Attendees")),
                "city": plain(p.get("City")) or "",
                "status": status,
                "type": plain(p.get("Event Type")) or [],
                "delivery": plain(p.get("Time Delivery")) or "",
                "pickup": plain(p.get("Pick Up Date and Time")) or "",
                "readyBy": plain(p.get("Food Ready by")) or "",
                "location": plain(p.get("Location")) or "",
                "url": row.get("url") or "",
            }
        if not page.get("has_more"):
            return out
        cursor = page.get("next_cursor")
