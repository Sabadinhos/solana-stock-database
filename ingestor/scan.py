#!/usr/bin/env python3
"""D1-1: full paginated scan of the StonkFun API + depth measurement.

First ingestor cycle (PRODUCT delta 1). Fetches pages in parallel (honoring
429/Retry-After), writes each page to data/raw/pages/page_XXXXXX.jsonl (incremental
persistence), concatenates in order and produces data/graph-snapshot.json + report.

Usage:
    python scan.py --max-pages 20      # test
    python scan.py                     # full scan
"""
import argparse
import collections
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://www.stonkfun.xyz/api/public/v1"
PAGE_SIZE = 100
WORKERS = 8
TIMEOUT = 40
MAX_RETRIES = 6

HERE = os.path.dirname(os.path.abspath(__file__))
# Runtime data is mounted at /app/data in production. Keep the local default
# compatible with the repository layout.
DATA_DIR = os.environ.get("SDB_DATA_DIR", os.path.join(os.path.dirname(HERE), "data"))
RAW_DIR = os.path.join(DATA_DIR, "raw")
PAGES_DIR = os.path.join(RAW_DIR, "pages")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


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
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = (2 ** attempt) + 1
            log(f"    retry {attempt+1}/{MAX_RETRIES} (network error: {e}) -> {wait:.0f}s")
            time.sleep(min(wait, 30.0))
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {url}")


def get_total():
    d = fetch_json(f"{BASE}/stats")
    return d.get("data", {}).get("tokens", {}).get("total", 0)


def fetch_page(page):
    """Return (page, tokens). Write the page to disk as soon as it arrives."""
    url = f"{BASE}/tokens?page={page}&pageSize={PAGE_SIZE}"
    data = fetch_json(url)
    batch = data.get("data", {}).get("tokens", [])
    p_path = os.path.join(PAGES_DIR, f"page_{page:06d}.jsonl")
    with open(p_path, "w", encoding="utf-8") as f:
        for t in batch:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return page, batch


def scan_tokens(expected_pages):
    os.makedirs(PAGES_DIR, exist_ok=True)
    # clear pages from a previous cycle (new cycle = new write)
    for f in os.listdir(PAGES_DIR):
        os.remove(os.path.join(PAGES_DIR, f))

    pages = list(range(1, expected_pages + 1))
    log(f"Fetching {len(pages)} pages with {WORKERS} workers...")
    t0 = time.time()
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_page, p): p for p in pages}
        done_count = 0
        for fut in concurrent.futures.as_completed(futs):
            page, batch = fut.result()
            results[page] = batch
            done_count += 1
            if done_count % 50 == 0 or done_count == len(pages):
                n = sum(len(v) for v in results.values())
                log(f"  {done_count}/{len(pages)} pages, {n} tokens "
                    f"({time.time()-t0:.0f}s)")

    # sort and build the final list, truncating at the first empty page
    tokens = []
    last_nonempty = 0
    for p in sorted(results):
        if results[p]:
            tokens.extend(results[p])
            last_nonempty = p
        elif p > last_nonempty and last_nonempty > 0:
            break

    # dedupe by mint: marketCap pagination drifts during the scan (prices change),
    # so the same mint can appear on two pages. Keep the last occurrence.
    dedup = {}
    for t in tokens:
        dedup[t["mint"]] = t
    tokens = list(dedup.values())
    log(f"Scan complete: {len(tokens)} unique tokens "
        f"(pages 1..{last_nonempty}, {time.time()-t0:.1f}s)")

    # write the consolidated raw file (never overwrite: rename the old one)
    raw_path = os.path.join(RAW_DIR, "tokens.jsonl")
    if os.path.exists(raw_path):
        ts = time.strftime("%Y%m%d-%H%M%S")
        os.rename(raw_path, os.path.join(RAW_DIR, f"tokens-{ts}.jsonl"))
    with open(raw_path, "w", encoding="utf-8") as f:
        for t in tokens:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return tokens


def build_graph(tokens):
    by_mint = {t["mint"]: t for t in tokens}
    all_mints = set(by_mints := set(by_mint.keys()))

    records = []
    cycles = []
    for t in tokens:
        chain = []
        seen = {t["mint"]}
        cur = t
        depth = 0
        is_cycle = False
        while cur.get("quote", {}).get("mint") in all_mints:
            nxt_mint = cur["quote"]["mint"]
            if nxt_mint in seen:
                is_cycle = True
                break
            seen.add(nxt_mint)
            chain.append({
                "mint": nxt_mint,
                "symbol": by_mint[nxt_mint].get("symbol"),
                "category": by_mint[nxt_mint].get("quote", {}).get("category"),
            })
            depth += 1
            cur = by_mint[nxt_mint]
        if not is_cycle:
            depth += 1
        terminal = cur.get("quote", {})
        records.append({
            "mint": t["mint"],
            "symbol": t.get("symbol"),
            "name": t.get("name"),
            "mode": t.get("mode"),
            "creator": t.get("creator"),
            "transferFeeBps": (t.get("transferFee") or {}).get("bps"),
            "depth": depth,
            "is_cycle": is_cycle,
            "terminal": {
                "mint": terminal.get("mint"),
                "symbol": terminal.get("symbol"),
                "name": terminal.get("name"),
                "category": terminal.get("category"),
                "categoryLabel": terminal.get("categoryLabel"),
            },
            "chain": chain,
            "market": t.get("market"),
        })
        if is_cycle:
            cycles.append(t["mint"])

    return records, cycles


def report(tokens, records, cycles):
    n = len(tokens)
    print(f"\n{'='*70}")
    print("REPORT D1-1: StonkFun scan + backing depth")
    print(f"{'='*70}")
    print(f"Tokens scanned: {n}")

    hist = collections.Counter(r["depth"] for r in records)
    print("\n[1] Depth histogram (hops to the terminal asset):")
    for d in sorted(hist):
        pct = 100.0 * hist[d] / n
        print(f"    depth={d:>2}: {hist[d]:>6}  ({pct:5.1f}%)  {'#' * int(round(pct/2))}")

    cat = collections.Counter(r["terminal"]["category"] for r in records)
    print("\n[2] Tokens by terminal asset category:")
    for c, cnt in cat.most_common():
        print(f"    {c:<12} {cnt:>6}  ({100.0*cnt/n:5.1f}%)")

    chained = [r for r in records if r["depth"] > 1]
    print("\n[3] Backing chains:")
    print(f"    profundidade > 1: {len(chained)} ({100.0*len(chained)/n:.3f}%)")
    print(f"    cycles detected: {len(cycles)}")
    d3 = sum(1 for r in records if r["depth"] >= 3)
    print(f"    profundidade >= 3: {d3} ({100.0*d3/n:.3f}%)")

    by_depth = sorted(records, key=lambda r: -r["depth"])
    print("\n[4] Top 20 deepest chains:")
    for r in by_depth[:20]:
        path = " -> ".join([r["symbol"]] + [c["symbol"] for c in r["chain"]]
                           + [r["terminal"]["symbol"]])
        print(f"    depth={r['depth']:<2} {r['mint']}  {path[:110]}")

    modes = collections.Counter(t.get("mode") for t in tokens)
    print(f"\n[5] Modos: {dict(modes)}")
    with_fee = sum(1 for t in tokens if t.get("transferFee", {}).get("bps"))
    print(f"    tokens with transferFee: {with_fee}")
    creators = len({t.get("creator") for t in tokens if t.get("creator")})
    print(f"    distinct creators: {creators}")

    return {
        "total": n,
        "depth_histogram": dict(hist),
        "terminal_categories": dict(cat),
        "chained_count": len(chained),
        "depth_gte_3": d3,
        "cycle_count": len(cycles),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args()

    if args.max_pages:
        expected = args.max_pages
    else:
        total = get_total()
        expected = (total // PAGE_SIZE) + 12  # headroom for growth during the scan
        log(f"Stats: {total} tokens -> ~{expected} pages estimated")

    tokens = scan_tokens(expected)
    if not tokens:
        print("No tokens scanned.")
        sys.exit(1)

    records, cycles = build_graph(tokens)
    summary = report(tokens, records, cycles)

    snap_path = os.path.join(DATA_DIR, "graph-snapshot.json")
    snapshot = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totalTokens": len(tokens),
        "summary": summary,
        "records": records,
    }
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    print(f"\nSnapshot written to: {snap_path}")


if __name__ == "__main__":
    main()
