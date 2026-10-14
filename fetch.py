"""SDB — helpers de fetch com rate-limit (compartilhados).

`paginate` varre um endpoint paginado em ondas, deduplica por `mint` em tempo real e
para quando uma onda não traz nenhum mint novo (detecta a cauda-fantasma da API, que
repete os mesmos itens além do fim).
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
WAVE = 40          # páginas por onda
MAX_PAGES = 2000   # teto de segurança


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
    raise RuntimeError(f"falhou após {MAX_RETRIES} tentativas: {url}")


def paginate(endpoint, key, page_size=100, workers=WORKERS, max_pages=None,
             log=lambda *a, **k: None):
    """Varre `GET /{endpoint}`, extrai `data.{key}`, dedupe por mint, retorna itens únicos."""
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
        log(f"  /{endpoint} páginas {pages[0]}-{pages[-1]}: {len(items)} itens "
            f"({time.time()-t0:.0f}s)")
        page += WAVE
        if new == 0:
            log(f"  /{endpoint}: cauda-fantasma detectada em {page-WAVE}, parando")
            break
    return items


def get_total_tokens():
    try:
        s = fetch_json(f"{BASE}/stats")
        return s.get("data", {}).get("tokens", {}).get("total", 0)
    except Exception:
        return 0
