"""Embed data/all.json (gzip + base64) into a single self-contained HTML team viewer."""
import base64
import re
import gzip
import json
import sys
from pathlib import Path

from common import DATA, ROOT

OUT = ROOT / "bball_team_viewer.html"

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>D2 / D3 / JUCO Basketball Team Viewer</title>
<style>
__CSS__
</style>
</head>
<body>
<div class="viz-root" id="root">
<header>
  <h1>Basketball Team Viewer <span class="badge">men's · __SEASONS__</span></h1>
  <div class="tabs" id="views" role="group" aria-label="View">
    <button data-v="teams" aria-pressed="true">Teams</button><button data-v="leaders" aria-pressed="false">Stat leaders</button>
  </div>
  <div class="tabs" id="levels" role="group" aria-label="Level"></div>
  <label class="ctl team-only">Conference <select id="conf"></select></label>
  <label class="ctl team-only">Season <select id="season"></select></label>
  <div class="toggle" role="group" aria-label="Stat mode">
    <button data-mode="pg" aria-pressed="true">Per game</button><button data-mode="tot" aria-pressed="false">Totals</button>
  </div>
  <div class="spacer"></div>
  <input type="search" id="search" placeholder="Find a player (all levels)…" aria-label="Find a player">
  <button class="icon-btn" id="theme" title="Toggle light/dark">◐</button>
</header>
<main>
  <aside id="teams" aria-label="Teams"></aside>
  <section class="team" id="team"><div class="loading">Loading data…</div></section>
</main>
<dialog id="player"><div class="dh"><h3 id="pname"></h3><button class="x" onclick="this.closest('dialog').close()" aria-label="Close">×</button></div><div class="db" id="pbody"></div></dialog>
</div>
<script id="data" type="application/octet-stream">__DATA__</script>
<script>
let DATA = null;
async function loadData() {
  const b64 = document.getElementById('data').textContent.trim();
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  return JSON.parse(text);
}

// --- Team colors: each school's brand color, muted so pages stay calm ---
function hexToHsl(hex) {
  let h = hex.replace('#', ''); if (h.length === 3) h = [...h].map(c => c + c).join('');
  const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const hue = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(hue * 60 + 360) % 360, s, l];
}
const hsl = (h, s, l) => `hsl(${h.toFixed(0)} ${(s * 100).toFixed(0)}% ${(l * 100).toFixed(0)}%)`;
const isDark = () => { const r = document.documentElement.dataset.theme; return r ? r === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; };
function teamPalette(hex) {
  if (!hex) return null;
  const [h, s, l] = hexToHsl(hex);
  if (l > 0.88 || l < 0.04 || s < 0.08) return { neutral: true };   // white/black/gray: fall back to the level hue
  const sm = Math.min(s, 0.62) * 0.72;                               // mute the saturation
  const dark = isDark();
  return {
    team: hsl(h, sm, dark ? 0.40 : 0.38), team2: hsl((h + 12) % 360, sm * 0.9, dark ? 0.27 : 0.27),
    soft: hsl(h, sm * 0.7, dark ? 0.2 : 0.93), ink: hsl(h, sm, dark ? 0.82 : 0.28), chip: hsl(h, sm, dark ? 0.6 : 0.5),
  };
}
const TEAM_VARS = ['--team', '--team-2', '--team-soft', '--team-ink'];
function applyTeamColors(hex) {
  const root = $('root'), pal = teamPalette(hex);
  if (!pal || pal.neutral) { TEAM_VARS.forEach(v => root.style.removeProperty(v)); return; }
  root.style.setProperty('--team', pal.team); root.style.setProperty('--team-2', pal.team2);
  root.style.setProperty('--team-soft', pal.soft); root.style.setProperty('--team-ink', pal.ink);
}
const chipColor = hex => { const pal = teamPalette(hex); return pal && !pal.neutral ? pal.chip : 'var(--accent)'; };
const LEVEL_ORDER = ['D2', 'D3', 'JUCO'];
const state = { view: 'teams', level: null, conf: null, team: null, season: null, mode: 'pg', sort: { key: 'ppg', dir: -1 } };
// Stat-leaders view: '' means "all" for conference / season / class.
const lead = { conf: '', season: null, cls: '', minGp: 10, top: 100, sort: { key: 'ppg', dir: -1 } };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const per = (s, k) => (s && s.gp ? s[k] / s.gp : null);
const PCT = v => v == null ? '' : (v > 1 ? v / 100 : v).toFixed(3).replace(/^0/, '');
const F1 = v => v == null || isNaN(v) ? '' : v.toFixed(1);
const INT = v => v == null ? '' : String(v);
function htStr(p) { if (p.ht_in) return `${Math.floor(p.ht_in / 12)}-${p.ht_in % 12}`; return p.ht || ''; }

// Column definitions: [key, label, value(p), format, numeric]
const BIO_COLS = [
  ['num', '#', p => p.num ?? '', String, false],
  ['name', 'Player', p => p.name, String, false],
  ['pos', 'Pos', p => p.pos || '', String, false],
  ['ht', 'Ht', p => p.ht_in ?? -1, (v, p) => htStr(p), true],
  ['wt', 'Wt', p => p.wt ?? -1, (v, p) => p.wt ?? '', true],
  ['yr', 'Yr', p => classRank(p.yr), (v, p) => p.yr || '', false],
];
const PG_COLS = [
  ['gp', 'GP', p => p.stats?.gp, INT], ['gs', 'GS', p => p.stats?.gs, INT],
  ['mpg', 'MPG', p => p.stats?.mpg ?? per(p.stats, 'min'), F1],
  ['ppg', 'PPG', p => p.stats?.ppg ?? per(p.stats, 'pts'), F1],
  ['rpg', 'RPG', p => p.stats?.rpg ?? per(p.stats, 'reb'), F1],
  ['apg', 'APG', p => per(p.stats, 'ast'), F1],
  ['spg', 'SPG', p => per(p.stats, 'stl'), F1], ['bpg', 'BPG', p => per(p.stats, 'blk'), F1],
  ['tov', 'TO', p => per(p.stats, 'to'), F1],
  ['fg_pct', 'FG%', p => p.stats?.fg_pct, PCT], ['tp_pct', '3P%', p => p.stats?.tp_pct, PCT], ['ft_pct', 'FT%', p => p.stats?.ft_pct, PCT],
];
const TOT_COLS = [
  ['gp', 'GP', p => p.stats?.gp, INT], ['gs', 'GS', p => p.stats?.gs, INT], ['min', 'MIN', p => p.stats?.min, INT],
  ['pts', 'PTS', p => p.stats?.pts, INT], ['fgm', 'FGM', p => p.stats?.fgm, INT], ['fga', 'FGA', p => p.stats?.fga, INT],
  ['tpm', '3PM', p => p.stats?.tpm, INT], ['tpa', '3PA', p => p.stats?.tpa, INT], ['ftm', 'FTM', p => p.stats?.ftm, INT], ['fta', 'FTA', p => p.stats?.fta, INT],
  ['oreb', 'OREB', p => p.stats?.oreb, INT], ['dreb', 'DREB', p => p.stats?.dreb, INT], ['reb', 'REB', p => p.stats?.reb, INT],
  ['ast', 'AST', p => p.stats?.ast, INT], ['stl', 'STL', p => p.stats?.stl, INT], ['blk', 'BLK', p => p.stats?.blk, INT], ['to', 'TO', p => p.stats?.to, INT], ['pf', 'PF', p => p.stats?.pf, INT],
];
const TAIL_COLS = [
  ['hometown', 'Hometown', p => p.hometown || '', String, false],
  ['prev', 'Prev. school / HS', p => p.prev || p.hs || '', String, false],
];
const cols = () => [...BIO_COLS, ...(state.mode === 'pg' ? PG_COLS : TOT_COLS).map(c => [...c, true]), ...TAIL_COLS];

const levels = () => LEVEL_ORDER.filter(l => DATA.levels[l]);
const confs = () => Object.keys(DATA.levels[state.level]).sort();
const teams = () => DATA.levels[state.level][state.conf];
const confSeasons = () => [...new Set(Object.values(teams()).flatMap(t => Object.keys(t.seasons)))].sort().reverse();
const hasStats = s => Object.values(teams()).some(t => (t.seasons[s] || []).some(p => p.stats));

function renderControls() {
  $('levels').innerHTML = levels().map(l => `<button aria-pressed="${l === state.level}" data-l="${l}" style="--dot: var(--lvl-${l})">${l}</button>`).join('');
  $('conf').innerHTML = confs().map(c => `<option ${c === state.conf ? 'selected' : ''}>${esc(c)}</option>`).join('');
  $('season').innerHTML = confSeasons().map(s => `<option value="${s}" ${s === state.season ? 'selected' : ''}>${s}${hasStats(s) ? '' : ' (roster only)'}</option>`).join('');
}

function teamSummary(t) {
  const ps = t.seasons[state.season] || [];
  const top = ps.filter(p => p.stats?.gp).sort((a, b) => (b.stats.ppg ?? per(b.stats, 'pts')) - (a.stats.ppg ?? per(a.stats, 'pts')))[0];
  return { n: ps.length, top };
}

function renderTeams() {
  const names = Object.keys(teams()).sort();
  $('teams').innerHTML = names.map(n => {
    const t = teams()[n], s = teamSummary(t);
    const sub = !s.n ? 'no data this season' : `${s.n} players` + (s.top ? ` · ${esc(s.top.name)} ${F1(s.top.stats.ppg ?? per(s.top.stats, 'pts'))} ppg` : '');
    return `<button data-t="${esc(n)}" aria-current="${n === state.team}" style="--chip: ${chipColor(t.color)}">${esc(n)}${t.division ? `<span class="badge">${esc(t.division.replace('Division ', 'Div '))}</span>` : ''}<span class="sub">${sub}</span></button>`;
  }).join('');
}

function tile(k, v, s) { return `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s || ''}</div></div>`; }

function renderTeam() {
  const t = teams()[state.team];
  const el = $('team');
  if (!t) { applyTeamColors(null); el.innerHTML = '<div class="empty">Pick a team.</div>'; return; }
  applyTeamColors(t.color);
  const ps = (t.seasons[state.season] || []).slice();
  const site = t.site ? `<a href="${esc(t.site)}" target="_blank" rel="noopener">${esc(t.site.replace(/^https?:\/\//, ''))}</a>` : '';
  let head = `<div class="hero"><div class="row"><h2>${esc(state.team)}</h2>${t.division ? `<span class="badge">${esc(t.division)}</span>` : ''}</div>
    <div class="row"><span class="meta">${esc(state.level)} · ${esc(state.conf)} · ${state.season}</span>${site}</div></div>`;
  if (t.error) head += `<p class="note">Couldn't scrape this school: ${esc(t.error)}</p>`;
  if (!ps.length) { el.innerHTML = head + '<div class="empty">No roster or stats for this season.</div>'; return; }

  const withHt = ps.filter(p => p.ht_in);
  const avgHt = withHt.length ? withHt.reduce((a, p) => a + p.ht_in, 0) / withHt.length : null;
  const played = ps.filter(p => p.stats?.gp);
  const best = (f) => played.slice().sort((a, b) => (f(b) ?? -1) - (f(a) ?? -1))[0];
  const ppg = p => p.stats.ppg ?? per(p.stats, 'pts'), rpg = p => p.stats.rpg ?? per(p.stats, 'reb'), apg = p => per(p.stats, 'ast');
  let tiles = tile('Roster', ps.length, `${withHt.length} with height listed`);
  tiles += tile('Avg height', avgHt ? `${Math.floor(avgHt / 12)}′${(avgHt % 12).toFixed(1)}″` : '—', withHt.length ? `tallest ${htStr(withHt.sort((a, b) => b.ht_in - a.ht_in)[0])}` : '');
  for (const [k, f] of [['Top scorer', ppg], ['Top rebounder', rpg], ['Top passer', apg]]) {
    const b = played.length && best(f);
    tiles += tile(k, b ? F1(f(b)) : '—', b ? esc(b.name) : 'no stats');
  }

  const C = cols();
  const { key, dir } = state.sort;
  const col = C.find(c => c[0] === key) || C.find(c => c[0] === 'name');
  ps.sort((a, b) => {
    let x = col[2](a), y = col[2](b);
    if (x == null || x === '') return 1; if (y == null || y === '') return -1;
    return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * dir;
  });
  const thead = '<tr>' + C.map(c => `<th class="${c[4] ? 'n' : ''} ${c[0] === col[0] ? 'sorted' : ''}" data-k="${c[0]}" aria-sort="${c[0] === col[0] ? (dir > 0 ? 'ascending' : 'descending') : 'none'}">${c[1]}</th>`).join('') + '</tr>';
  const rows = ps.map((p, i) => '<tr data-i="' + i + '">' + C.map(c => {
    const v = c[2](p); const txt = c[3](v, p);
    const cls = [c[4] ? 'n' : '', c[0] === 'name' ? 'name' : '', c[0] === col[0] ? 'sorted' : '', !p.stats && c[4] && c[0] !== 'ht' && c[0] !== 'wt' ? 'muted' : ''].join(' ');
    return `<td class="${cls}">${esc(txt === -1 ? '' : txt)}</td>`;
  }).join('') + '</tr>').join('');
  el.innerHTML = head + `<div class="tiles">${tiles}</div><div class="table-wrap"><table><thead>${thead}</thead><tbody>${rows}</tbody></table></div>
    <p class="note">Click a column to sort; click a player for their season-by-season history. Source: ${t.platform === 'sidearm' ? 'school Sidearm site' : t.platform === 'presto' ? 'NJCAA stats feed + school PrestoSports roster' : 'NJCAA stats feed'}.</p>`;
  el._rows = ps;
}

// --- Player history: same name AND matching identity (hometown, height, team continuity) ---
const normName = n => { n = String(n || ''); if (n.includes(',')) { const [l, f] = n.split(','); n = f + ' ' + l; }
  return n.toLowerCase().replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '').replace(/-/g, ' ').replace(/[^a-z ]/g, '').split(/\s+/).filter(Boolean).sort().join(' '); };
let INDEX = null;
function buildIndex() {
  INDEX = new Map();
  for (const [level, cs] of Object.entries(DATA.levels)) for (const [conf, ts] of Object.entries(cs)) for (const [team, t] of Object.entries(ts))
    for (const [season, ps] of Object.entries(t.seasons)) for (const p of ps) {
      const k = normName(p.name); if (!k) continue;
      if (!INDEX.has(k)) INDEX.set(k, []);
      INDEX.get(k).push({ level, conf, team, season, p });
    }
}

// Hometowns come as "Lincoln, Neb.", "Omaha, NE", "Saint Paul, Minnesota", "Milwaukee"...
const STATES = { al: 'al', ala: 'al', alabama: 'al', ak: 'ak', alaska: 'ak', az: 'az', ariz: 'az', arizona: 'az', ar: 'ar', ark: 'ar', arkansas: 'ar',
  ca: 'ca', calif: 'ca', cal: 'ca', california: 'ca', co: 'co', colo: 'co', colorado: 'co', ct: 'ct', conn: 'ct', connecticut: 'ct', de: 'de', del: 'de', delaware: 'de',
  dc: 'dc', fl: 'fl', fla: 'fl', florida: 'fl', ga: 'ga', georgia: 'ga', hi: 'hi', hawaii: 'hi', id: 'id', idaho: 'id', il: 'il', ill: 'il', illinois: 'il',
  in: 'in', ind: 'in', indiana: 'in', ia: 'ia', iowa: 'ia', ks: 'ks', kan: 'ks', kans: 'ks', kansas: 'ks', ky: 'ky', kentucky: 'ky', la: 'la', louisiana: 'la',
  me: 'me', maine: 'me', md: 'md', maryland: 'md', ma: 'ma', mass: 'ma', massachusetts: 'ma', mi: 'mi', mich: 'mi', michigan: 'mi', mn: 'mn', minn: 'mn', minnesota: 'mn',
  ms: 'ms', miss: 'ms', mississippi: 'ms', mo: 'mo', missouri: 'mo', mt: 'mt', mont: 'mt', montana: 'mt', ne: 'ne', neb: 'ne', nebr: 'ne', nebraska: 'ne',
  nv: 'nv', nev: 'nv', nevada: 'nv', nh: 'nh', nj: 'nj', nm: 'nm', ny: 'ny', nc: 'nc', nd: 'nd', oh: 'oh', ohio: 'oh', ok: 'ok', okla: 'ok', oklahoma: 'ok',
  or: 'or', ore: 'or', oregon: 'or', pa: 'pa', penn: 'pa', pennsylvania: 'pa', ri: 'ri', sc: 'sc', sd: 'sd', tn: 'tn', tenn: 'tn', tennessee: 'tn',
  tx: 'tx', tex: 'tx', texas: 'tx', ut: 'ut', utah: 'ut', vt: 'vt', vermont: 'vt', va: 'va', virginia: 'va', wa: 'wa', wash: 'wa', washington: 'wa',
  wv: 'wv', wi: 'wi', wis: 'wi', wisc: 'wi', wisconsin: 'wi', wy: 'wy', wyo: 'wy', wyoming: 'wy',
  'new hampshire': 'nh', 'new jersey': 'nj', 'new mexico': 'nm', 'new york': 'ny', 'north carolina': 'nc', 'north dakota': 'nd', 'rhode island': 'ri',
  'south carolina': 'sc', 'south dakota': 'sd', 'west virginia': 'wv', 'n.h': 'nh', 'n.j': 'nj', 'n.m': 'nm', 'n.y': 'ny', 'n.c': 'nc', 'n.d': 'nd',
  'r.i': 'ri', 's.c': 'sc', 's.d': 'sd', 'w.va': 'wv', 'd.c': 'dc' };
function place(hometown) {
  if (!hometown) return null;
  const [cityRaw, ...rest] = String(hometown).split('/')[0].split(',');  // "Morrison, Colo. / Bear Creek" -> hometown only
  const city = cityRaw.toLowerCase().replace(/\bst\.?\s/g, 'saint ').replace(/\bft\.?\s/g, 'fort ').replace(/\bmt\.?\s/g, 'mount ')
    .replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
  const stRaw = rest.join(',').toLowerCase().trim().replace(/\.$/, '');
  const st = STATES[stRaw] || STATES[stRaw.replace(/\./g, '')] || (stRaw ? stRaw.replace(/[^a-z ]/g, '') : null);
  return city ? { city, st } : null;
}
function samePlace(a, b) {
  if (!a || !b) return null;                       // unknown
  if (a.city !== b.city && !a.city.startsWith(b.city + ' ') && !b.city.startsWith(a.city + ' ')) return false;
  return a.st && b.st ? a.st === b.st : true;
}
const HT_TOL = 2;                                 // inches: players grow (or get re-measured) a little
function sameHeight(a, b) { return a.ht_in && b.ht_in ? Math.abs(a.ht_in - b.ht_in) <= HT_TOL : null; }
const teamWords = name => name.toLowerCase().replace(/university|college|community|state|of|the|at|junior|-/g, ' ').split(/\s+/).filter(w => w.length > 3);
const prevNames = (p, team) => p.prev && teamWords(team).some(w => p.prev.toLowerCase().includes(w));

// Is record b the same person as record a? true / false
function sameIdentity(a, b) {
  if (a.season === b.season) return a.team === b.team && a.level === b.level;  // one team per season
  const home = samePlace(place(a.p.hometown), place(b.p.hometown));
  const ht = sameHeight(a.p, b.p);
  const prevLink = a.team !== b.team && (prevNames(a.p, b.team) || prevNames(b.p, a.team));
  if (ht === false) return false;
  // A roster naming the other school as a previous stop outweighs a hometown mismatch
  // (some sites list the high school's town instead of the hometown).
  if (home === false && !prevLink) return false;
  if (a.team === b.team && a.level === b.level) return true;                    // same program, other season
  // A move between programs needs positive evidence: hometown, or the previous-school field naming the other team.
  return home === true || prevLink;
}

// Hard contradictions: a different hometown, or heights more than HT_TOL apart.
const conflicts = (a, b) => sameHeight(a.p, b.p) === false
  || (samePlace(place(a.p.hometown), place(b.p.hometown)) === false && !(a.team !== b.team && (prevNames(a.p, b.team) || prevNames(b.p, a.team))));

// Grow a career outward from the clicked season, linking only records that pass sameIdentity.
function career(anchor) {
  const all = INDEX.get(normName(anchor.p.name)) || [];
  const linked = [anchor], pool = all.filter(r => r.p !== anchor.p);
  let grew = true;
  while (grew) {
    grew = false;
    for (let i = pool.length - 1; i >= 0; i--) {
      const r = pool[i];
      if (linked.some(l => l.season === r.season && (l.team !== r.team || l.level !== r.level))) continue;
      if (linked.some(l => sameIdentity(l, r)) && !linked.some(l => conflicts(l, r))) {
        linked.push(r); pool.splice(i, 1); grew = true;
      }
    }
  }
  const sort = arr => arr.sort((a, b) => a.season.localeCompare(b.season) || a.team.localeCompare(b.team));
  return { linked: sort(linked), others: sort(pool) };
}

let OTHERS = [];
function showPlayer(anchor) {
  if (!INDEX) buildIndex();
  if (typeof anchor === 'string') {                    // deep link by name: pick the most recent record
    const hits = INDEX.get(normName(anchor)) || [];
    anchor = hits.slice().sort((a, b) => b.season.localeCompare(a.season))[0];
    if (!anchor) return;
  }
  const { linked, others } = career(anchor);
  $('pname').textContent = anchor.p.name;
  const C = [['season', 'Season'], ['team', 'Team'], ['lvl', 'Level'], ['yr', 'Yr'], ['ht', 'Ht'], ['wt', 'Wt'], ...PG_COLS.map(c => [c[0], c[1], c[2], c[3]])];
  const row = h => '<tr>' + C.map(c => {
    if (c[0] === 'season') return `<td>${h.season}</td>`;
    if (c[0] === 'team') return `<td><span class="dot" style="--c: ${chipColor(DATA.levels[h.level][h.conf][h.team].color)}"></span>${esc(h.team)}</td>`;
    if (c[0] === 'lvl') return `<td>${esc(h.level)}</td>`;
    if (c[0] === 'yr') return `<td>${esc(h.p.yr || '')}</td>`;
    if (c[0] === 'ht') return `<td class="n">${esc(htStr(h.p))}</td>`;
    if (c[0] === 'wt') return `<td class="n">${esc(h.p.wt ?? '')}</td>`;
    return `<td class="n">${esc(c[3](c[2](h.p)))}</td>`;
  }).join('') + '</tr>';
  const last = linked[linked.length - 1].p;
  const home = linked.map(h => h.p.hometown).filter(Boolean).pop();  // most recent listing
  const bio = [last.pos && `Pos ${last.pos}`, home, last.hs && `HS: ${last.hs}`, last.prev && `Prev: ${last.prev}`].filter(Boolean).map(esc).join(' · ');
  applyTeamColors(DATA.levels[anchor.level][anchor.conf][anchor.team].color);
  const head = `<thead><tr>${C.map(c => `<th class="${['season','team','lvl','yr'].includes(c[0]) ? '' : 'n'}">${c[1]}</th>`).join('')}</tr></thead>`;
  OTHERS = others;
  const otherList = others.length ? `<h4 class="others-head">Other players named ${esc(anchor.p.name)} <span class="meta">— not linked: hometown or height doesn't match, or there isn't enough info to tell</span></h4>
    <div class="table-wrap"><table class="others"><thead><tr><th>Season</th><th>Team</th><th>Level</th><th>Hometown</th><th class="n">Ht</th><th class="n">PPG</th></tr></thead><tbody>
    ${others.map((h, i) => `<tr data-o="${i}"><td>${h.season}</td><td><span class="dot" style="--c: ${chipColor(DATA.levels[h.level][h.conf][h.team].color)}"></span>${esc(h.team)}</td><td>${esc(h.level)}</td><td>${esc(h.p.hometown || '—')}</td><td class="n">${esc(htStr(h.p) || '—')}</td><td class="n">${esc(F1(h.p.stats?.ppg ?? per(h.p.stats, 'pts')))}</td></tr>`).join('')}
    </tbody></table></div>` : '';
  const crossTeam = new Set(linked.map(h => h.level + h.team)).size > 1;
  $('pbody').innerHTML = `<p class="meta">${bio}</p><div class="table-wrap"><table>${head}<tbody>${linked.map(row).join('')}</tbody></table></div>
    ${crossTeam ? `<p class="note">Seasons at different schools are linked only when the hometown matches or the roster's previous-school field names the other school, and listed heights are within ${HT_TOL}″.</p>` : ''}
    ${otherList}`;
  if (!$('player').open) $('player').showModal();
  // Closing the popup restores the current page's colors.
  $('player').onclose = () => (state.view === 'leaders' ? applyTeamColors(null) : applyTeamColors(teams()[state.team]?.color));
}
$('pbody').onclick = e => { const tr = e.target.closest('tr[data-o]'); if (tr) showPlayer(OTHERS[+tr.dataset.o]); };

// --- Stat leaders: every player-season in the level, filtered and ranked ---
const CLASS_ORDER = ['Fr', 'So', 'Jr', 'Sr', 'Gr'];
const CLASS_WORDS = [['fr', 'first'], ['so', 'soph'], ['jr', 'jun'], ['sr', 'sen'], ['gr', 'grad', '5th', 'fifth']];
const REDSHIRT = /^(r-|rs-|rs\s|r\.|redshirt)\s*/i;
function classOf(yr) {
  const y = String(yr || '').toLowerCase().replace(REDSHIRT, '');
  const i = CLASS_WORDS.findIndex(ws => ws.some(w => y.startsWith(w)));
  return i < 0 ? null : CLASS_ORDER[i];
}
const classRank = yr => { const c = classOf(yr); return c ? CLASS_ORDER.indexOf(c) + (REDSHIRT.test(String(yr)) ? 0.5 : 0) : null; };

// Percent leaders need volume: minimum attempts per game.
const PCT_MIN = { fg_pct: ['fga', 3, 'FGA'], tp_pct: ['tpa', 1, '3PA'], ft_pct: ['fta', 1, 'FTA'] };

function leaderRows() {
  const out = [];
  for (const [conf, ts] of Object.entries(DATA.levels[state.level])) {
    if (lead.conf && conf !== lead.conf) continue;
    for (const [team, t] of Object.entries(ts)) for (const [season, ps] of Object.entries(t.seasons)) {
      if (lead.season && season !== lead.season) continue;
      for (const p of ps) {
        if (!p.stats || !p.stats.gp || p.stats.gp < lead.minGp) continue;
        if (lead.cls && classOf(p.yr) !== lead.cls) continue;
        out.push({ ...p, team, conf, season, _p: p });
      }
    }
  }
  return out;
}

// "Mid-America Intercollegiate Athletics Association" -> "MIAA"; "NJCAA Region 06" -> "Region 06".
function confShort(name) {
  if (/^NJCAA /.test(name)) return name.replace('NJCAA ', '');
  const words = name.replace(/-/g, ' ').split(/\s+/).filter(w => !/^(of|the|and|&)$/i.test(w));
  return words.length < 2 ? name : words.map(w => /^\d+$/.test(w) ? w : w[0].toUpperCase()).join('');
}

function leaderCols() {
  const stat = (state.mode === 'pg' ? PG_COLS : TOT_COLS).map(c => [...c, true]);
  return [
    ['name', 'Player', p => p.name, String, false],
    ['team', 'Team', p => p.team, String, false],
    ...(lead.conf ? [] : [['conf', 'Conf', p => p.conf, v => confShort(v), false]]),
    ['season', 'Season', p => p.season, String, false],
    ['yr', 'Yr', p => classRank(p.yr), (v, p) => p.yr || '', false],
    ['pos', 'Pos', p => p.pos || '', String, false],
    ['ht', 'Ht', p => p.ht_in ?? null, (v, p) => htStr(p), true],
    ...stat,
  ];
}

function statSeasons() {
  const ss = new Set();
  for (const ts of Object.values(DATA.levels[state.level])) for (const t of Object.values(ts))
    for (const [s, ps] of Object.entries(t.seasons)) if (ps.some(p => p.stats)) ss.add(s);
  return [...ss].sort().reverse();
}

function renderLeaders() {
  const el = $('team');
  applyTeamColors(null);
  const seasons = statSeasons();
  if (lead.season === null || (lead.season && !seasons.includes(lead.season))) lead.season = seasons[0] || '';
  if (lead.conf && !DATA.levels[state.level][lead.conf]) lead.conf = '';
  const C = leaderCols();
  const col = C.find(c => c[0] === lead.sort.key) || C.find(c => c[0] === (state.mode === 'pg' ? 'ppg' : 'pts'));
  const dir = lead.sort.dir;
  let rows = leaderRows();
  const q = PCT_MIN[col[0]];
  if (q) rows = rows.filter(p => (p.stats[q[0]] ?? 0) >= q[1] * p.stats.gp);
  // Ties (e.g. everyone in one season or class) rank by scoring, then newest season, then name.
  const score = C.find(c => c[0] === (state.mode === 'pg' ? 'ppg' : 'pts'))[2];
  rows.sort((a, b) => {
    const x = col[2](a), y = col[2](b);
    if (x == null || x === '') return 1; if (y == null || y === '') return -1;
    const d = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
    return d * dir || (score(b) ?? -1) - (score(a) ?? -1) || b.season.localeCompare(a.season) || a.name.localeCompare(b.name);
  });
  const total = rows.length;
  if (lead.top) rows = rows.slice(0, lead.top);

  const opt = (v, label, cur) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(label)}</option>`;
  const filters = `<div class="filters">
    <label class="ctl">Conference <select id="lconf">${opt('', 'All conferences', lead.conf)}${Object.keys(DATA.levels[state.level]).sort().map(c => opt(c, c, lead.conf)).join('')}</select></label>
    <label class="ctl">Season <select id="lseason">${opt('', 'All seasons', lead.season)}${seasons.map(s => opt(s, s, lead.season)).join('')}</select></label>
    <label class="ctl">Class <select id="lcls">${opt('', 'All', lead.cls)}${CLASS_ORDER.map(c => opt(c, c, lead.cls)).join('')}</select></label>
    <label class="ctl">Min GP <input type="number" id="lgp" min="0" value="${lead.minGp}"></label>
    <label class="ctl">Show <select id="ltop">${[25, 50, 100, 250, 0].map(n => `<option value="${n}" ${n === lead.top ? 'selected' : ''}>${n ? 'Top ' + n : 'All'}</option>`).join('')}</select></label>
  </div>`;
  const thead = '<tr><th class="n">Rk</th>' + C.map(c => `<th class="${c[4] ? 'n' : ''} ${c[0] === col[0] ? 'sorted' : ''}" data-k="${c[0]}" aria-sort="${c[0] === col[0] ? (dir > 0 ? 'ascending' : 'descending') : 'none'}">${c[1]}</th>`).join('') + '</tr>';
  const body = rows.map((p, i) => `<tr data-i="${i}"><td class="rank">${i + 1}</td>` + C.map(c => {
    const txt = c[3](c[2](p), p);
    const dot = c[0] === 'team' ? `<span class="dot" style="--c: ${chipColor(DATA.levels[state.level][p.conf][p.team].color)}"></span>` : '';
    const title = c[0] === 'conf' ? ` title="${esc(p.conf)}"` : '';
    return `<td class="${c[4] ? 'n' : ''} ${c[0] === 'name' ? 'name' : ''} ${c[0] === col[0] ? 'sorted' : ''}"${title}>${dot}${esc(txt ?? '')}</td>`;
  }).join('') + '</tr>').join('');
  const scope = `${state.level} · ${lead.conf || 'all conferences'} · ${lead.season || 'all seasons'}${lead.cls ? ' · ' + lead.cls : ''}`;
  el.innerHTML = `<div class="plain-head"><h2>Stat leaders</h2><span class="meta">${esc(scope)} · ${total} player-seasons with ≥ ${lead.minGp} GP</span></div>${filters}
    ${rows.length ? `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${body}</tbody></table></div>` : '<div class="empty">No players match these filters.</div>'}
    <p class="note">Click any column to sort (click again to flip). Season sorts by year; Yr sorts by class (Fr → Gr, redshirts just after their class). ${q ? `${col[1]} leaders need ≥ ${q[1]} ${q[2]} per game. ` : ''}Click a player for their history.</p>`;
  el._rows = rows;
}

function pickDefaults() {
  if (!state.level) state.level = levels()[0];
  if (!confs().includes(state.conf)) state.conf = confs()[0];
  const ss = confSeasons();
  if (!ss.includes(state.season)) state.season = ss.find(hasStats) || ss[0];
  if (!teams()[state.team]) state.team = Object.keys(teams()).sort()[0];
}
function render() {
  pickDefaults(); renderControls();
  $('root').dataset.level = state.level;
  const leaders = state.view === 'leaders';
  document.querySelectorAll('#views button').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === state.view));
  $('teams').classList.toggle('hidden', leaders);
  document.querySelectorAll('.team-only').forEach(e => e.classList.toggle('hidden', leaders));
  if (leaders) renderLeaders(); else { renderTeams(); renderTeam(); }
}
const rerender = () => (state.view === 'leaders' ? renderLeaders() : renderTeam());

$('views').onclick = e => { const v = e.target.dataset.v; if (v) { state.view = v; render(); } };
$('levels').onclick = e => { const l = e.target.dataset.l; if (l) { state.level = l; state.conf = null; state.team = null; render(); } };
$('conf').onchange = e => { state.conf = e.target.value; state.team = null; render(); };
$('season').onchange = e => { state.season = e.target.value; render(); };
$('teams').onclick = e => { const b = e.target.closest('button'); if (b) { state.team = b.dataset.t; renderTeams(); renderTeam(); } };
document.querySelector('.toggle').onclick = e => { const m = e.target.dataset.mode; if (!m) return; state.mode = m;
  document.querySelectorAll('.toggle button').forEach(b => b.setAttribute('aria-pressed', b.dataset.mode === m));
  if (!cols().some(c => c[0] === state.sort.key)) state.sort = { key: m === 'pg' ? 'ppg' : 'pts', dir: -1 };
  if (!leaderCols().some(c => c[0] === lead.sort.key)) lead.sort = { key: m === 'pg' ? 'ppg' : 'pts', dir: -1 };
  rerender(); };
const ASC_FIRST = ['name', 'pos', 'yr', 'num', 'hometown', 'prev', 'team', 'conf'];
$('team').onchange = e => {
  if (state.view !== 'leaders') return;
  const v = e.target.value;
  if (e.target.id === 'lconf') lead.conf = v;
  else if (e.target.id === 'lseason') lead.season = v;
  else if (e.target.id === 'lcls') lead.cls = v;
  else if (e.target.id === 'lgp') lead.minGp = Math.max(0, +v || 0);
  else if (e.target.id === 'ltop') lead.top = +v;
  else return;
  renderLeaders();
};
$('team').onclick = e => {
  if (state.view === 'leaders') {
    const th = e.target.closest('th[data-k]');
    if (th) { const k = th.dataset.k; lead.sort = { key: k, dir: lead.sort.key === k ? -lead.sort.dir : (ASC_FIRST.includes(k) ? 1 : -1) }; renderLeaders(); return; }
    const tr = e.target.closest('tbody tr');
    if (tr) { const r = $('team')._rows[+tr.dataset.i]; showPlayer({ level: state.level, conf: r.conf, team: r.team, season: r.season, p: r._p }); }
    return;
  }
  const th = e.target.closest('th');
  if (th) { const k = th.dataset.k; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (['name', 'pos', 'yr', 'num', 'hometown', 'prev'].includes(k) ? 1 : -1) }; renderTeam(); return; }
  const tr = e.target.closest('tbody tr');
  if (tr) showPlayer({ level: state.level, conf: state.conf, team: state.team, season: state.season, p: $('team')._rows[+tr.dataset.i] });
};
$('search').onchange = e => {
  const q = normName(e.target.value); if (!q) return; if (!INDEX) buildIndex();
  const hit = INDEX.get(q) || [...INDEX.entries()].find(([k]) => q.split(' ').every(w => k.includes(w)))?.[1];
  if (hit) showPlayer(hit.slice().sort((a, b) => b.season.localeCompare(a.season))[0]); else alert('No player found');
};
$('theme').onclick = () => { const r = document.documentElement; const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; r.dataset.theme = dark ? 'light' : 'dark'; render(); };
// Deep links: #level=JUCO&conf=...&team=Hutchinson&season=2024-25&player=Name&theme=dark
const h = new URLSearchParams(location.hash.slice(1));
if (h.get('theme')) document.documentElement.dataset.theme = h.get('theme');
loadData().then(d => { DATA = d; start(); }).catch(err => { $('team').innerHTML = `<div class="empty">Couldn't load the data: ${esc(err.message)}</div>`; });
function start() {
for (const k of ['view', 'level', 'conf', 'team', 'season']) if (h.get(k)) state[k] = h.get(k);
if (h.get('sort')) lead.sort = { key: h.get('sort'), dir: h.get('dir') === 'asc' ? 1 : -1 };
if (h.has('lseason')) lead.season = h.get('lseason');
if (state.level && !DATA.levels[state.level]) state.level = null;
if (state.level && h.get('team') && !h.get('conf')) state.conf = Object.keys(DATA.levels[state.level]).find(c => DATA.levels[state.level][c][state.team]) || null;
render();
if (h.get('player')) showPlayer(h.get('player'));
}
</script>
</body>
</html>
"""


POS_WORDS = {"guard": "G", "forward": "F", "center": "C", "wing": "W", "post": "P", "point guard": "PG"}
CLASSES = [("fr", "Fr."), ("first", "Fr."), ("so", "So."), ("jun", "Jr."), ("jr", "Jr."), ("sen", "Sr."), ("sr", "Sr."),
           ("gr", "Gr."), ("5th", "Gr."), ("fifth", "Gr.")]


def norm_pos(pos):
    """'GUARD' / 'Guard/Forward' / '*' -> 'G' / 'G/F' / None."""
    parts = [x.strip().lower() for x in re.split(r"[/,-]", pos or "") if x.strip() and x.strip() != "*"]
    out = [POS_WORDS.get(x, x.upper()) for x in parts]
    return "/".join(out) or None


def norm_yr(yr):
    """'SO' / 'Sophomore' / 'RS-Sophomore' / 'R-Jr.' -> 'So.' / 'So.' / 'R-So.' / 'R-Jr.'."""
    y = (yr or "").strip()
    m = re.match(r"(r-|rs-|rs\s+|r\.|redshirt\s+)?(.*)", y, re.I)
    rest = m.group(2).lower()
    for prefix, label in CLASSES:
        if rest.startswith(prefix):
            return ("R-" if m.group(1) else "") + label
    return y or None


def compact(data):
    """Drop fields the viewer never reads so the embedded payload stays small."""
    for confs in data["levels"].values():
        for teams in confs.values():
            for team in teams.values():
                for k in ("stats_from_site", "error", "platform_note"):
                    team.pop(k, None)
                for players in team["seasons"].values():
                    for p in players:
                        p.pop("bio", None)
                        p["pos"], p["yr"] = norm_pos(p.get("pos")), norm_yr(p.get("yr"))
                        if "/" in (p.get("hometown") or "") and not p.get("hs"):
                            # Some rosters combine "Hometown / High School" in one column.
                            home, _, hs = p["hometown"].partition("/")
                            p["hometown"], p["hs"] = home.strip(), hs.strip() or None
                        if p.get("ht_in"):
                            p.pop("ht", None)
                        for k in [k for k, v in p.items() if v in (None, "")]:
                            del p[k]
    return data


def main(source="all.json"):
    data = compact(json.loads((DATA / source).read_text(encoding="utf8")))
    raw = json.dumps(data, separators=(",", ":")).encode("utf8")
    payload = base64.b64encode(gzip.compress(raw, 9)).decode("ascii")
    seasons = data.get("seasons") or []
    label = f"{seasons[-1]} → {seasons[0]}" if seasons else "pilot"
    html = TEMPLATE.replace("__CSS__", (Path(__file__).with_name("viewer.css")).read_text(encoding="utf8"))
    html = html.replace("__SEASONS__", label).replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf8")
    (ROOT / "index.html").write_text(html, encoding="utf8")  # the GitHub Pages site
    print(f"raw JSON {len(raw) / 1e6:.1f} MB -> embedded {len(payload) / 1e6:.1f} MB")
    print("wrote", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(*sys.argv[1:])
