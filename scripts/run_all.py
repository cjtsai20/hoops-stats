"""Full scrape: every D2/D3 member and every NJCAA region, men's, this season plus the past two.

Reads data/schools.json (from build_lists.py); writes data/all.json for build_viewer.py and
data/failures.json listing schools that produced no data. Every page is cached, so reruns resume.
"""
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import njcaa
import sidearm
from common import DATA, fetch, paused, set_provider

MIN_SEASON = "2024-25"
CURRENT = "2026-27"
SEASONS = ["2026-27", "2025-26", "2024-25"]
STAT_SEASONS = [s for s in SEASONS if s != CURRENT]

_done = 0
_lock = threading.Lock()


def progress(total, label):
    global _done
    with _lock:
        _done += 1
        print(f"[{_done}/{total}] {label}", flush=True)


def base_of(url):
    return re.match(r"https?://[^/]+", url).group(0)


def discover(url):
    """Find the men's basketball section from a school's athletics homepage (for non-standard URLs)."""
    status, final, html = fetch(url)
    if status != 200:
        return None, None
    m = re.search(r'href="((?:https?://[^"/]+)?)/sports/(mens-basketball|mbkb|m-baskbl)\b', html)
    if not m:
        return None, None
    host = m.group(1) or base_of(final)
    return host, ("presto" if m.group(2) == "mbkb" else "sidearm")


def scrape_ncaa(s, total):
    base = base_of(s["url"])
    r = sidearm.scrape_school({"url": base}, MIN_SEASON)
    platform = "sidearm"
    if r.get("error"):
        host, kind = discover(s["url"])
        if host and kind == "sidearm" and host != base:
            r = sidearm.scrape_school({"url": host}, MIN_SEASON)
        elif host and kind == "presto":
            # PrestoSports D2/D3 school: rosters only for now (no stats parser for their team pages yet).
            rosters, site, platform, color = njcaa.school_rosters(host, SEASONS)
            r = {"seasons": {k: sidearm.merge(v, []) for k, v in rosters.items()}, "site": site, "color": color}
    team = {"site": r.get("site", base), "platform": platform, "color": r.get("color"),
            "seasons": r.get("seasons", {}), "error": r.get("error") if not r.get("seasons") else None}
    progress(total, f"{s['level']} {s['name']}: {team['error'] or str(len(team['seasons'])) + ' seasons'}")
    return s, team


def juco_school(member, region, stats_by_season, total):
    rosters, site, platform, color = ({}, member["link"], "none", None)
    if member["link"]:
        rosters, site, platform, color = njcaa.school_rosters(member["link"], SEASONS)
    feed, division = {}, None
    for season, (players, sch) in stats_by_season.items():
        feed[season] = [njcaa.to_player(p) for p in players if p["schoolTenantId"] == member["tenantId"]]
        if member["tenantId"] in sch:
            division = division or sch[member["tenantId"]]["divisionName"]
    backfilled = []
    if platform == "sidearm":
        missing = [s for s in stats_by_season if not feed[s]]
        site_stats = njcaa.sidearm_site_stats(site, missing)
        feed.update(site_stats)
        backfilled = sorted(site_stats)
    team_seasons = {}
    for season in SEASONS:
        roster, stats = rosters.get(season, []), feed.get(season, [])
        if roster or stats:
            team_seasons[season] = sidearm.merge(roster, stats)
    team = {"site": site, "platform": platform, "color": color, "division": division,
            "stats_from_site": backfilled, "seasons": team_seasons}
    progress(total, f"JUCO {region} {member['name']}: {platform}, {len(team_seasons)} seasons")
    return region, member["name"], team


def main():
    lists = json.loads((DATA / "schools.json").read_text(encoding="utf8"))
    schools, regions = lists["ncaa"], lists["njcaa_regions"]
    for s in schools:
        if not paused(s["url"]):
            set_provider(base_of(s["url"]), "sidearm")  # pace from the very first request

    # NJCAA stats + members per region (small, fast API calls).
    juco_jobs = []
    for r in regions:
        stats = {s: njcaa.region_stats(r["region_id"], s) for s in STAT_SEASONS}
        members = {m["tenantId"]: m for m in njcaa.members(r["region_id"], "2025-26")}
        for players, sch in stats.values():
            for tid, sc in sch.items():
                members.setdefault(tid, {"tenantId": tid, "name": sc["displayName"], "link": None})
        for m in members.values():
            juco_jobs.append((m, r["conf"], stats))
        print(f"[JUCO] {r['conf']}: {len(members)} schools", flush=True)

    total = len(schools) + len(juco_jobs)
    out = {"generated": datetime.now().isoformat(timespec="minutes"), "gender": "men",
           "seasons": SEASONS, "levels": {}}
    failures = []
    with ThreadPoolExecutor(max_workers=60) as ncaa_pool, ThreadPoolExecutor(max_workers=40) as juco_pool:
        nf = [ncaa_pool.submit(scrape_ncaa, s, total) for s in schools]
        jf = [juco_pool.submit(juco_school, m, region, stats, total) for m, region, stats in juco_jobs]
        for f in nf:
            s, team = f.result()
            if team["seasons"]:
                out["levels"].setdefault(s["level"], {}).setdefault(s["conf"], {})[s["name"]] = team
            else:
                failures.append({"level": s["level"], "conf": s["conf"], "name": s["name"], "url": s["url"],
                                 "error": team["error"]})
        for f in jf:
            region, name, team = f.result()
            if team["seasons"]:
                out["levels"].setdefault("JUCO", {}).setdefault(region, {})[name] = team
            else:
                failures.append({"level": "JUCO", "conf": region, "name": name, "url": team["site"],
                                 "error": f"no data ({team['platform']})"})
    (DATA / "all.json").write_text(json.dumps(out), encoding="utf8")
    (DATA / "failures.json").write_text(json.dumps(failures, indent=1), encoding="utf8")
    n = sum(len(ts) for cs in out["levels"].values() for ts in cs.values())
    print(f"wrote all.json: {n} teams; {len(failures)} schools with no data (see failures.json)")


if __name__ == "__main__":
    sys.exit(main())
