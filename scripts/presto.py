"""Roster parser for PrestoSports school sites (/sports/mbkb/<season>/roster)."""
import re

from bs4 import BeautifulSoup

from common import PARSER, clean, height_in, num

FIELDS = {
    "number": "num", "position": "pos", "year": "yr", "height": "ht", "weight": "wt",
    "hometown": "hometown", "highschool": "hs", "previous_school": "prev", "previousschool": "prev",
}


def is_presto(html):
    return "prestosports" in html.lower() or "/sports/mbkb/" in html


def _text(cell):
    for label in cell.select("span.label"):
        label.decompose()
    return clean(cell.get_text(" "))


def parse_roster(html):
    s = BeautifulSoup(html, PARSER)
    players = []
    for table in s.find_all("table"):
        cap = clean(table.caption.get_text(" ")) if table.caption else ""
        if cap and "roster" not in cap.lower():
            continue
        rows = table.select("tbody tr")
        if not rows:
            continue
        if not rows[0].find(attrs={"data-field": True}):
            players = _parse_by_headers(table)
            if players:
                break
            continue
        for tr in rows:
            p = {}
            for cell in tr.find_all(["td", "th"], attrs={"data-field": True}):
                field = cell["data-field"].lower()
                if "last_name" in field or "first_name" in field:
                    a = cell.find("a")
                    p["name"] = clean((a or cell).get_text(" "))
                    if a and a.get("href"):
                        p["bio"] = a["href"]
                elif ":" in field:
                    # Combined columns like 'hometown:/:highschool'.
                    keys = [FIELDS.get(k) for k in field.split(":") if k not in ("/", "")]
                    vals = [v.strip() for v in _text(cell).split("/")]
                    for k, v in zip(keys, vals):
                        if k:
                            p[k] = v
                elif field in FIELDS:
                    p[FIELDS[field]] = _text(cell)
            if p.get("name"):
                p["ht_in"] = height_in(p.get("ht"))
                p["wt"] = num(p.get("wt", ""))
                players.append(p)
        if players:
            break
    return players


def _parse_by_headers(table):
    """Older PrestoSports template: no data-field attributes, so map columns by header text."""
    from sidearm import ROSTER_COLS

    heads = [ROSTER_COLS.get(clean(th.get_text(" ")).lower()) for th in table.select("thead th")]
    if "name" not in heads:
        return []
    players = []
    for tr in table.select("tbody tr"):
        # Skip mobile-only duplicate cells (e.g. a jersey badge shown only on small screens).
        cells = [c for c in tr.find_all(["td", "th"], recursive=False) if "d-md-none" not in (c.get("class") or [])]
        if len(cells) != len(heads):
            continue
        p = {}
        for key, cell in zip(heads, cells):
            if key == "name":
                a = cell.find("a")
                p["name"] = clean((a or cell).get_text(" "))
                if a and a.get("href"):
                    p["bio"] = a["href"]
            elif key:
                p[key] = _text(cell)
        for combo, second in (("hometown_hs", "hs"), ("hometown_prev", "prev")):
            if combo in p:
                p["hometown"], _, p[second] = (x.strip() for x in p.pop(combo).partition("/"))
        if p.get("name"):
            p["ht_in"] = height_in(p.get("ht"))
            p["wt"] = num(p.get("wt", ""))
            players.append(p)
    return players


def season_links(html):
    out = {}
    for season in re.findall(r"/sports/mbkb/(20\d\d-\d\d)/roster", html):
        out.setdefault(season, f"/sports/mbkb/{season}/roster")
    return out
