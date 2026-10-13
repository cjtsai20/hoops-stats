"""NJCAA region stats from the public Ardor SportsHub feed, with ht/wt from each school's roster page."""
import json
import re
from urllib.parse import urlencode

import presto
import sidearm
from common import fetch, num, theme_color

STATS_API = "https://0wtr7r0cl7.execute-api.us-east-2.amazonaws.com/prod/tenant/stats"
GRAPHQL = "https://public-graphql-api.ardorsportshub.com/public/graphql"
MEMBERS_QUERY = "query($t: ID!, $s: String!){ tenantMembers(tenantId: $t, season: $s){ members { tenantId name link } } }"

STAT_KEYS = {
    "gp": "gp", "gs": "gs", "min": "min", "minpg": "mpg",
    "fgm": "fgm", "fga": "fga", "fgptg": "fg_pct",
    "fgm3": "tpm", "fga3": "tpa", "fgptg3": "tp_pct",
    "ftm": "ftm", "fta": "fta", "ftptg": "ft_pct",
    "pts": "pts", "ptspg": "ppg", "oreb": "oreb", "dreb": "dreb", "treb": "reb", "trebpg": "rpg",
    "pf": "pf", "ast": "ast", "to": "to", "stl": "stl", "blk": "blk",
}


def region_stats(region_id, season, gender_id=1, sport="mbkb"):
    """All players + schools for one region-season (both NJCAA divisions)."""
    players, schools, offset = [], {}, 0
    while True:
        q = {"tenant_id": region_id, "season": season, "sport": sport, "sport_id": 2, "gender_id": gender_id,
             "include_players": "true", "include_games": "false", "player_limit": 200, "player_offset": offset}
        status, _, text = fetch(f"{STATS_API}?{urlencode(q)}")
        if status != 200:
            break
        d = json.loads(text)
        players += d.get("players") or []
        for s in d.get("schools") or []:
            schools[s["schoolTenantId"]] = s
        if not d.get("hasMorePlayers"):
            break
        offset = d["nextPlayerOffset"]
    return players, schools


def members(region_id, season):
    body = {"query": MEMBERS_QUERY, "variables": {"t": region_id, "s": season}}
    status, _, text = fetch(GRAPHQL, method="POST", json=body)
    if status != 200:
        return []
    return ((json.loads(text).get("data") or {}).get("tenantMembers") or {}).get("members") or []


def school_rosters(link, seasons):
    """{season: [roster players]} from a JUCO's own site (Sidearm or PrestoSports)."""
    base = re.match(r"https?://[^/]+", link).group(0)
    out = {}
    # Probe with the last completed season; next season's roster often isn't posted yet.
    probe = seasons[1] if len(seasons) > 1 else seasons[0]
    status, final, html = fetch(f"{base}/sports/mbkb/{probe}/roster")
    if status == 200 and presto.is_presto(html):
        base = re.match(r"https?://[^/]+", final).group(0)
        # Some sites default to headshot cards; the list view has the table.
        view = "" if presto.parse_roster(html) else "?view=list"
        for season in seasons:
            st, _, h = fetch(f"{base}/sports/mbkb/{season}/roster{view}")
            if st == 200:
                players = presto.parse_roster(h)
                if players:
                    out[season] = players
        return out, base, "presto", theme_color(html)
    status, final, html = fetch(f"{base}/sports/{sidearm.SPORT}/roster")
    if status == 200 and sidearm.is_sidearm(html):
        base = re.match(r"https?://[^/]+", final).group(0)
        links = sidearm.season_links(html, "roster")
        current = sidearm.page_season(html)
        if current:
            links.setdefault(current, f"/sports/{sidearm.SPORT}/roster")
        for season in seasons:
            if season in links:
                st, _, h = fetch(base + links[season])
                if st == 200 and sidearm.page_season(h) == season:
                    out[season] = sidearm.parse_roster(h)
        return out, base, "sidearm", theme_color(html)
    return out, base, "unknown", None


def sidearm_site_stats(base, seasons):
    """Backfill seasons the NJCAA feed is missing from a Sidearm JUCO's own /stats pages."""
    _, _, html = fetch(f"{base}/sports/{sidearm.SPORT}/stats")
    links = sidearm.season_links(html, "stats")
    out = {}
    for season in seasons:
        if season in links:
            st, _, h = fetch(base + links[season])
            if st == 200:
                rows = sidearm.parse_stats(h)
                if rows:
                    out[season] = rows
    return out


def to_player(p):
    stats = {}
    for src, key in STAT_KEYS.items():
        v = (p.get("stats") or {}).get(src)
        if v is not None:
            stats[key] = num(str(v))
    out = {"name": p["displayName"], "num": p.get("number"), "pos": (p.get("position") or "").upper() or None,
           "stats": stats}
    for k, src in (("yr", "year"), ("ht", "height"), ("hometown", "hometown"), ("hs", "highSchool")):
        if p.get(src):
            out[k] = p[src]
    if p.get("weight"):
        out["wt"] = num(str(p["weight"]))
    return out
