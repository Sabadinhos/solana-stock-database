"""SDB: shared rate-limited fetch helpers.

`paginate` scans a paginated endpoint in waves, dedupes by `mint` on the fly and
stops when a wave brings no new mint (detects the API phantom tail, which
repeats the same items past the end).
"""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request

BASE = "https://www.stonkfun.xyz/api/public/v1"
TIMEOUT = 40
MAX_RETRIES = 6
WORKERS = 8
WAVE = 40          # pages per wave
MAX_PAGES = 2000   # safety cap


def fetch_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                wait = float(ra) if ra else (2 ** attempt) + 1
                time.sleep(min(wait, 30.0))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(min((2 ** attempt) + 1, 30.0))
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {url}")


def paginate(endpoint, key, page_size=100, workers=WORKERS, max_pages=None,
             log=lambda *a, **k: None):
    """Scan `GET /{endpoint}`, extract `data.{key}`, dedupe by mint, return unique items."""
    seen = set()
    items = []
    page = 1
    cap = max_pages or MAX_PAGES

    def _f(p):
        d = fetch_json(f"{BASE}/{endpoint}?page={p}&pageSize={page_size}")
        return d.get("data", {}).get(key, []) if isinstance(d.get("data"), dict) else []

    t0 = time.time()
    while page <= cap:
        pages = list(range(page, min(page + WAVE, cap + 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            results = dict(zip(pages, ex.map(_f, pages)))
        new = 0
        for p in sorted(results):
            for it in results[p]:
                m = it.get("mint")
                if m is None or m not in seen:
                    if m is not None:
                        seen.add(m)
                    items.append(it)
                    new += 1
        log(f"  /{endpoint} pages {pages[0]}-{pages[-1]}: {len(items)} items "
            f"({time.time()-t0:.0f}s)")
        page += WAVE
        if new == 0:
            log(f"  /{endpoint}: phantom tail detected at {page-WAVE}, stopping")
            break
    return items


def get_total_tokens():
    try:
        s = fetch_json(f"{BASE}/stats")
        return s.get("data", {}).get("tokens", {}).get("total", 0)
    except Exception:
        return 0
