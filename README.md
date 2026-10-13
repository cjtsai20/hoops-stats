# hoops-stats

Rosters and player stats for **NCAA Division II, Division III and NJCAA (JUCO)** men's basketball:
2026-27 rosters plus 2025-26 and 2024-25 season stats. The site is a single page (`index.html`) with:

- **Teams**: pick a level → conference → team for a sortable roster + stats table, shown in the team's colors.
- **Stat leaders**: rank every player in a level by any stat, filtered by conference, season and class.
- **Player history**: click a player for their season-by-season line, including moves between levels
  (matched by name, so common names can collide).

## Sources

- D2 / D3: each school's own athletics site (Sidearm Sports roster and cumulative-stats pages); member lists
  and current conferences come from the NCAA directory.
- JUCO: season stats from the NJCAA's public stats feed, heights/weights from school roster pages.

Crawling follows each site's robots.txt and crawl-delay, paces requests per hosting provider, and caches pages.

## Known gaps

- Schools hosted on PrestoSports (about 60 D2/D3 schools and most JUCO roster pages) are not included yet.
- The NJCAA feed covers only part of each region, and 2024-25 is thinner than 2025-26.
- Conferences are current (2026-27) affiliations.

## Rebuilding

```
cd scripts
python build_lists.py   # school + region lists
python run_all.py       # crawl (cached; resumable) -> data/all.json
python build_viewer.py  # -> index.html
```

Requires Python 3.12+, `requests`, `beautifulsoup4`, `lxml`.
