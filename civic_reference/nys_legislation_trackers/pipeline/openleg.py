"""Small NY Senate Open Legislation v3 client. Never exposes or logs the API key."""
import os, time, json, threading
import urllib.request, urllib.parse, urllib.error

BASE = "https://legislation.nysenate.gov"
KEYFILE = os.path.expanduser("~/.config/nycur/openleg_key")
MIN_INTERVAL = 0.27  # about 3.7 requests per second
_lock = threading.Lock()
_last = [0.0]
STATS = {"requests": 0, "throttled_429": 0, "server_5xx": 0, "retries": 0}


def _key():
    k = os.environ.get("NYS_OPENLEG_KEY")
    if not k and os.path.exists(KEYFILE):
        k = open(KEYFILE).read().strip()
    if not k:
        raise RuntimeError("No Open Legislation key: set NYS_OPENLEG_KEY or write ~/.config/nycur/openleg_key")
    return k


def _pace():
    with _lock:
        wait = _last[0] + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def get(path, params=None, retries=6, raw=False):
    """GET a path under BASE. params may hold lists (repeated keys). Returns parsed JSON (or text if raw)."""
    q = list((params or {}).items())
    flat = []
    for k, v in q:
        if isinstance(v, (list, tuple)):
            flat += [(k, x) for x in v]
        else:
            flat.append((k, v))
    flat.append(("key", _key()))
    url = BASE + path + "?" + urllib.parse.urlencode(flat)
    delay = 1.0
    last_err = None
    for attempt in range(retries + 1):
        _pace()
        STATS["requests"] += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nycur-nys-tracker"}), timeout=60) as r:
                body = r.read().decode("utf-8")
                return body if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s" % e.code
            if e.code == 429:
                STATS["throttled_429"] += 1
            elif e.code >= 500:
                STATS["server_5xx"] += 1
            elif e.code == 404:
                return None
            else:
                raise RuntimeError("HTTP %s for %s" % (e.code, path))
        except Exception as e:  # network errors: report the type only, never the URL
            last_err = type(e).__name__
        STATS["retries"] += 1
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise RuntimeError("Failed after retries (%s): %s" % (last_err, path))


def paginate(path, params=None, page=1000, max_items=None):
    """Yield items from a limit/offset list endpoint (offset starts at 1) until an empty page."""
    offset = 1
    n = 0
    while True:
        p = dict(params or {})
        p.update({"limit": page, "offset": offset})
        d = get(path, p)
        items = ((d or {}).get("result") or {}).get("items") or []
        if not items:
            return
        for it in items:
            yield it
            n += 1
            if max_items and n >= max_items:
                return
        offset += len(items)
        if len(items) < page:
            return


def total(path, params=None):
    p = dict(params or {})
    p.update({"limit": 1, "offset": 1})
    return (get(path, p) or {}).get("total")
