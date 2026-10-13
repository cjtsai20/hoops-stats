"""Parsers for Sidearm Sports school sites (roster table + 'Overall Individual Statistics')."""
import re

from bs4 import BeautifulSoup

from common import PARSER, clean, fetch, height_in, norm_name, num, season_key, theme_color

SPORT = "mens-basketball"

ROSTER_COLS = {
    "#": "num", "no.": "num", "no": "num",
    "name": "name", "full name": "name", "player": "name", "first name": "first", "last name": "last",
    "pos.": "pos", "pos": "pos", "position": "pos",
    "ht.": "ht", "ht": "ht", "height": "ht", "hgt.": "ht", "hgt": "ht",
    "wt.": "wt", "wt": "wt", "weight": "wt", "wgt.": "wt", "wgt": "wt",
    "yr.": "yr", "yr": "yr", "year": "yr", "cl.": "yr", "class": "yr", "academic year": "yr",
    "hometown": "hometown", "high school": "hs", "previous school": "prev",
    "hometown/high school": "hometown_hs", "hometown/previous school": "hometown_prev",
    "hometown / high school": "hometown_hs", "last school": "prev", "previous school(s)": "prev",
}

# (group header, sub header) -> canonical stat key
STAT_COLS = {
    ("gp", ""): "gp", ("gs", ""): "gs",
    ("minutes", "tot"): "min", ("minutes", "avg"): "mpg", ("min", ""): "min", ("mpg", ""): "mpg",
    ("fg", "fgm"): "fgm", ("fg", "fga"): "fga", ("fg", "fg%"): "fg_pct",
    ("3pt", "3pt"): "tpm", ("3pt", "3pta"): "tpa", ("3pt", "3pt%"): "tp_pct",
    ("ft", "ftm"): "ftm", ("ft", "fta"): "fta", ("ft", "ft%"): "ft_pct",
    ("scoring", "pts"): "pts", ("scoring", "avg"): "ppg",
    ("rebounds", "off"): "oreb", ("rebounds", "def"): "dreb", ("rebounds", "tot"): "reb", ("rebounds", "avg"): "rpg",
    ("pf", ""): "pf", ("ast", ""): "ast", ("to", ""): "to", ("stl", ""): "stl", ("blk", ""): "blk",
}


def is_sidearm(html):
    return "sidearm" in html.lower()


def season_links(html, kind):
    """All /sports/<sport>/<kind>/<season> links on a page -> {'2025-26': absolute path}."""
    out = {}
    for path in re.findall(rf'/sports/{SPORT}/{kind}/(20\d\d-(?:20)?\d\d)(?=["\'?#/])', html):
        out.setdefault(season_key(path), f"/sports/{SPORT}/{kind}/{path}")
    return out


def page_season(html):
    """Season named in the roster table caption, e.g. "2022-23 Men's Basketball Roster"."""
    for cap in re.findall(r"<caption[^>]*>(.*?)</caption>", html, re.S | re.I):
        if re.search(r"staff|coach|statistic", cap, re.I):
            continue
        key = season_key(re.sub(r"<[^>]+>", " ", cap))
        if key:
            return key
    return None


def parse_roster(html):
    s = BeautifulSoup(html, PARSER)
    # Pick the player table by its columns; captions vary ("2022-23 Men's Basketball" with no "Roster").
    table, heads = None, []
    for tb in s.find_all("table"):
        cap = clean(tb.caption.get_text(" ")) if tb.caption else ""
        if re.search(r"staff|coach", cap, re.I):
            continue
        heads = [ROSTER_COLS.get(clean(th.get_text(" ")).lower()) for th in tb.select("thead th")]
        if ("name" in heads or "first" in heads) and ("ht" in heads or "pos" in heads):
            table = tb
            break
    if table is None:
        return []
    players = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) != len(heads):
            continue
        p = {}
        for key, cell in zip(heads, cells):
            if key:
                p[key] = clean(cell.get_text(" "))
        if "first" in p or "last" in p:
            p["name"] = clean(f"{p.pop('first', '')} {p.pop('last', '')}")
        p["name"] = re.sub(r"\s+\d+$", "", p.get("name", ""))  # some sites append a stray digit
        if "hometown_hs" in p:
            p["hometown"], _, p["hs"] = (x.strip() for x in p.pop("hometown_hs").partition("/"))
        if "hometown_prev" in p:
            p["hometown"], _, p["prev"] = (x.strip() for x in p.pop("hometown_prev").partition("/"))
        if not p.get("name"):
            continue
        a = tr.find("a", href=re.compile(rf"/sports/{SPORT}/roster/[^/]+/\d+"))
        if a:
            p["bio"] = a["href"]
        p["ht_in"] = height_in(p.get("ht"))
        p["wt"] = num(p.get("wt", ""))
        players.append(p)
    return players


def _flat_headers(table):
    rows = table.select("thead tr")
    if not rows:
        return []
    top = rows[0].find_all("th")
    sub = [clean(th.get_text(" ")).lower() for th in rows[1].find_all("th")] if len(rows) > 1 else []
    out, i = [], 0
    for th in top:
        g = clean(th.get_text(" ")).lower()
        span = int(th.get("colspan") or 1)
        if span == 1:
            out.append((g, ""))
        else:
            out.extend((g, sub[i + k] if i + k < len(sub) else "") for k in range(span))
            i += span
    return out


def parse_stats(html):
    """Season totals from the 'Overall Individual Statistics' table."""
    s = BeautifulSoup(html, PARSER)
    table = None
    for tb in s.find_all("table"):
        cap = clean(tb.caption.get_text(" ")) if tb.caption else ""
        if cap.lower() == "overall individual statistics":
            table = tb
            break
    if table is None:
        return []
    heads = _flat_headers(table)
    out = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < len(heads):
            continue
        row = {}
        for (g, sub), cell in zip(heads, cells):
            if g == "#":
                row["num"] = clean(cell.get_text())
            elif g == "player":
                a = cell.find("a", class_="hide-on-medium-down") or cell.find("a")
                if a is None:
                    for mobile in cell.select(".hide-on-large"):
                        mobile.decompose()  # mobile duplicate: "<jersey> Last, First"
                row["name"] = clean(a.get_text() if a else cell.get_text(" "))
            elif (g, sub) in STAT_COLS:
                row[STAT_COLS[(g, sub)]] = num(cell.get_text())
        if row.get("name") and not re.match(r"(totals?|opponents?|team)\b", row["name"].lower()):
            if any(norm_name(r["name"]) == norm_name(row["name"]) for r in out):
                continue  # a few source pages list the same player twice
            out.append(row)
    return out


def merge(roster, stats):
    """Attach stats rows to roster players by name, then by jersey number; keep unmatched stats rows."""
    by_name = {norm_name(p["name"]): p for p in roster}
    by_num = {p.get("num"): p for p in roster if p.get("num")}
    players = [dict(p, name=_display(p["name"])) for p in roster]
    index = {id(p): i for i, p in enumerate(roster)}
    for st in stats:
        p = by_name.get(norm_name(st["name"]))
        if p is None and st.get("num"):
            p = by_num.get(st["num"].lstrip("0") or "0") or by_num.get(st["num"])
        # Stats rows are either flat (Sidearm) or {"name", "num", "stats", ...extra fields} (NJCAA).
        if "stats" in st:
            stat, extra = st["stats"], {k: v for k, v in st.items() if k not in ("name", "stats")}
        else:
            stat, extra = {k: v for k, v in st.items() if k not in ("name", "num")}, {"num": st.get("num")}
        if p is not None:
            target = players[index[id(p)]]
            target["stats"] = stat
            for k, v in extra.items():
                if v and not target.get(k):
                    target[k] = v
        else:
            players.append({"name": _display(st["name"]), **extra, "stats": stat})
    return players


def _display(name):
    if "," in name:
        last, first = name.split(",", 1)
        return clean(f"{first} {last}")
    return name


def scrape_school(school, min_season="2015-16"):
    base = school["url"].rstrip("/")
    status, final, html = fetch(f"{base}/sports/{SPORT}/roster")
    if status != 200:
        return {"error": f"roster HTTP {status}"}
    if not is_sidearm(html):
        return {"error": "not a Sidearm site"}
    base = re.match(r"https?://[^/]+", final).group(0)
    rosters = season_links(html, "roster")
    current = page_season(html)
    if current:
        rosters.setdefault(current, f"/sports/{SPORT}/roster")
    _, _, shtml = fetch(f"{base}/sports/{SPORT}/stats")
    stats_links = season_links(shtml, "stats")

    seasons = {}
    for season in sorted(set(rosters) | set(stats_links), reverse=True):
        if season < min_season:
            continue
        roster, stats = [], []
        if season in rosters:
            st, _, rh = fetch(base + rosters[season])
            # Some schools redirect every season URL to the current roster; only trust matching captions.
            if st == 200 and page_season(rh) == season:
                roster = parse_roster(rh)
        if season in stats_links:
            st, _, sh = fetch(base + stats_links[season])
            if st == 200:
                stats = parse_stats(sh)
        if roster or stats:
            seasons[season] = merge(roster, stats)
    return {"seasons": seasons, "site": base, "color": theme_color(html)}
