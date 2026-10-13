"""Shared helpers: polite cached fetching, robots.txt checks, name/height normalization."""
import hashlib
import ipaddress
import json
import socket
import re
import threading
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
DATA = ROOT / "data"
CACHE.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

UA = "Mozilla/5.0"
DELAY = 2.0

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"
_last_hit = {}
_robots = {}
_robots_lock = threading.Lock()
_local = threading.local()
# Cap in-flight requests overall.
_inflight = threading.BoundedSemaphore(8)

# Hundreds of school domains sit behind two providers, so on top of each site's own crawl-delay
# requests are paced per provider. Gaps widen automatically whenever a provider pushes back
# (PrestoSports answers bursts with HTTP 202 challenge pages).
PROVIDER_GAP = {"sidearm": 0.5, "presto": 4.0}
MAX_GAP = 30.0
_provider = {}          # host key -> "sidearm" | "presto"
_prov_next = {}         # provider -> earliest time the next request may start
_prov_lock = threading.Lock()


# PrestoSports sites sit on Amazon CloudFront (Sidearm on Rackspace), so DNS alone tells them apart.
# While PrestoSports is challenging us (HTTP 202), its hosts are skipped without sending any request.
PAUSED_PROVIDERS = {"presto"}
_cf_nets = None
_dns = {}


def _cloudfront_nets():
    global _cf_nets
    if _cf_nets is None:
        path, c = _cached("AWS-IP-RANGES")
        if c is None:
            r = requests.get("https://ip-ranges.amazonaws.com/ip-ranges.json", timeout=30)
            c = {"text": r.text}
            path.write_text(json.dumps(c), encoding="utf8")
        prefixes = json.loads(c["text"])["prefixes"]
        _cf_nets = [ipaddress.ip_network(x["ip_prefix"]) for x in prefixes if x["service"] == "CLOUDFRONT"]
    return _cf_nets


def on_cloudfront(host):
    host = host.split(":")[0]
    if host not in _dns:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
            _dns[host] = any(ip in net for net in _cloudfront_nets())
        except (OSError, ValueError):
            _dns[host] = False
    return _dns[host]


NOT_PRESTO = {"public-graphql-api.ardorsportshub.com", "ip-ranges.amazonaws.com"}  # CloudFront, but APIs


def paused(url):
    host = urlparse(url).netloc
    if host in NOT_PRESTO:
        return False
    prov = provider_of(host) or ("presto" if on_cloudfront(host) else None)
    return prov in PAUSED_PROVIDERS


def host_key(host):
    return host.lower().split(":")[0].removeprefix("www.")


def set_provider(host_or_url, provider):
    host = urlparse(host_or_url).netloc if "//" in host_or_url else host_or_url
    _provider[host_key(host)] = provider


def provider_of(host):
    return _provider.get(host_key(host))


def _sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = UA
    return _local.s


def _pace(host, delay):
    """Block until this host's crawl-delay and its provider's gap have both elapsed."""
    wait = delay - (time.time() - _last_hit.get(host_key(host), 0))
    if wait > 0:
        time.sleep(wait)
    prov = provider_of(host)
    if prov:
        with _prov_lock:
            start = max(time.time(), _prov_next.get(prov, 0))
            _prov_next[prov] = start + PROVIDER_GAP[prov]
        if start > time.time():
            time.sleep(start - time.time())


def _request(method, url, delay, **kw):
    host = urlparse(url).netloc
    _pace(host, delay)
    with _inflight:
        try:
            r = _sess().request(method, url, timeout=40, **kw)
            try:
                text = r.content.decode("utf-8")
            except UnicodeDecodeError:
                text = r.content.decode("cp1252", errors="replace")
            status, final = r.status_code, r.url
            if "ps-source-type" in r.headers:
                set_provider(host, "presto")
                set_provider(urlparse(final).netloc, "presto")
            elif "sidearm" in text[:300000].lower():
                set_provider(host, "sidearm")
                set_provider(urlparse(final).netloc, "sidearm")
        except requests.RequestException as e:
            status, final, text = 0, url, str(e)
    _last_hit[host_key(host)] = time.time()
    if status == 202:
        set_provider(host, "presto")
    prov = provider_of(host)
    if prov and (status in (202, 429) or status >= 500):
        with _prov_lock:
            old = PROVIDER_GAP[prov]
            PROVIDER_GAP[prov] = min(MAX_GAP, old * 1.5)
        if PROVIDER_GAP[prov] != old:
            print(f"  {prov} pushed back (HTTP {status}); gap now {PROVIDER_GAP[prov]:.1f}s", flush=True)
    return status, final, text


def _cached(key):
    path = CACHE / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
    return path, (json.loads(path.read_text(encoding="utf8")) if path.exists() else None)


def allowed(url):
    host = urlparse(url).netloc
    with _robots_lock:
        rp = _robots.get(host)
    if rp is None:
        robots_url = f"https://{host}/robots.txt"
        path, c = _cached("ROBOTS" + robots_url)
        if c is None:
            status, _, text = _request("GET", robots_url, DELAY)
            c = {"status": status, "text": text}
            if status in (200, 404):
                path.write_text(json.dumps(c), encoding="utf8")
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(c["text"].splitlines() if c["status"] == 200 else [])
        with _robots_lock:
            _robots[host] = rp
    # Respect explicit opt-outs aimed at Claude as well as the generic rules.
    return all(rp.can_fetch(agent, url) for agent in ("anthropic-ai", "Claude-Web", "ClaudeBot", "*"))


def fetch(url, method="GET", refresh=False, **kw):
    """Return (status, final_url, text). Cached on disk; paced per host (robots crawl-delay) and per provider."""
    key = hashlib.sha1((method + url + json.dumps(kw.get("json"), sort_keys=True)).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists() and not refresh:
        c = json.loads(path.read_text(encoding="utf8"))
        return c["status"], c["url"], c["text"]
    if paused(url):
        return 998, url, ""
    if not allowed(url):
        print(f"  robots.txt disallows {url}", flush=True)
        return 999, url, ""
    host = urlparse(url).netloc
    delay = max(DELAY, float(_robots[host].crawl_delay("*") or 0))
    for attempt in range(4):
        if attempt:
            time.sleep(delay * 2 ** attempt)
        status, final, text = _request(method, url, delay, **kw)
        if status not in (0, 202, 429) and status < 500:
            break
        if paused(url):
            return 998, url, ""
    if status not in (200, 404, 998):
        print(f"  HTTP {status} after retries: {url}", flush=True)
    if status in (200, 404):
        path.write_text(json.dumps({"status": status, "url": final, "text": text}), encoding="utf8")
    return status, final, text


def theme_color(html):
    """School brand color from <meta name="theme-color">, e.g. '#c41e25' (None if absent)."""
    for tag in re.findall(r"<meta[^>]+>", html or ""):
        if "theme-color" in tag:
            m = re.search(r"content\s*=\s*[\"']?(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b", tag)
            if m:
                return m.group(1).lower()
    return None


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def norm_name(name):
    """'Houston, Lazerek' / 'Lazerek  Houston' -> 'lazerek houston' for joining rosters to stats."""
    name = clean(name)
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first} {last}"
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name.lower())
    # Sorted tokens, because some sites swap first/last name fields.
    return " ".join(sorted(re.sub(r"[^a-z ]", "", name.replace("-", " ")).split()))


def height_in(ht):
    """'6-5', 6'5\", '6 ft 5' -> 77 inches (None if unparseable)."""
    m = re.match(r"\s*(\d)\s*(?:-|'|’|ft\.?|\s)\s*(\d{1,2})", ht or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def season_key(label):
    """'2025-2026' / '2025-26' -> '2025-26'."""
    m = re.search(r"(20\d\d)\s*-\s*(?:20)?(\d\d)", label or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def num(v):
    v = clean(v).replace(",", "")
    if v in ("", "-", "--"):
        return None
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return None
