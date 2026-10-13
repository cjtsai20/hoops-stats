"""Build data/schools.json: every D2/D3 member (NCAA directory) and every NJCAA region.

Conferences are current (2026-27) affiliations; schools that changed leagues show under today's conference.
"""
import json
from urllib.parse import urlencode

from common import DATA, fetch

NCAA_DIRECTORY = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&division={div}"
NJCAA = "404933495157163011"
STATS_API = "https://0wtr7r0cl7.execute-api.us-east-2.amazonaws.com/prod/tenant/stats"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
         "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
         "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24}
CONF_FIXES = {"Southern Intercol. Ath. Conf.": "Southern Intercollegiate Athletic Conference",
              "Old Dominion Athletic Conf.": "Old Dominion Athletic Conference",
              "Southern California Intercollegiate Athletic Conf.": "Southern California Intercollegiate Athletic Conference"}


def region_number(names):
    for n in names:
        tail = n.split()[-1]
        if tail.isdigit():
            return int(tail)
        if tail in ROMAN:
            return ROMAN[tail]
    return None


def ncaa_schools(div, level):
    status, _, text = fetch(NCAA_DIRECTORY.format(div=div))
    assert status == 200, status
    out = []
    for m in json.loads(text):
        if m["deactive"] != "N" or not m.get("athleticWebUrl"):
            continue
        url = m["athleticWebUrl"].strip()
        if not url.startswith("http"):
            url = "https://" + url
        conf = (m.get("conferenceName") or "Independent").strip()
        out.append({"level": level, "conf": CONF_FIXES.get(conf, conf), "name": m["nameOfficial"].strip(),
                    "url": url, "ncaa_id": m["orgId"], "state": (m.get("memberOrgAddress") or {}).get("state")})
    return out


def njcaa_regions():
    regions = {}
    for div in (1, 2, 3):
        cursor = None
        while True:
            q = {"tenant_id": NJCAA, "season": "2025-26", "sport": "mbkb", "sport_id": 2, "gender_id": 1,
                 "include_players": "false", "include_games": "false", "division": div, "limit": 50}
            if cursor:
                q["cursor"] = cursor
            status, _, text = fetch(f"{STATS_API}?{urlencode(q)}")
            d = json.loads(text)
            for s in d.get("schools") or []:
                regions.setdefault(s["regionTenantId"], set()).add(s["regionName"])
            if not d.get("hasMore"):
                break
            cursor = d["nextCursor"]
    out = []
    for rid, names in regions.items():
        n = region_number(names)
        out.append({"level": "JUCO", "conf": f"NJCAA Region {n:02d}" if n else sorted(names)[0], "region_id": rid})
    return sorted(out, key=lambda r: r["conf"])


def main():
    schools = ncaa_schools("II", "D2") + ncaa_schools("III", "D3")
    regions = njcaa_regions()
    (DATA / "schools.json").write_text(json.dumps({"ncaa": schools, "njcaa_regions": regions}, indent=1), encoding="utf8")
    print(f"{sum(s['level'] == 'D2' for s in schools)} D2, {sum(s['level'] == 'D3' for s in schools)} D3, "
          f"{len(regions)} NJCAA regions")


if __name__ == "__main__":
    main()
