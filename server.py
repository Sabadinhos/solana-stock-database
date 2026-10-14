"""SDB: REST API (D1-5), stdlib http.server, reading from SQLite (never StonkFun directly).

Endpoints:
  GET /api/stats                          -> live system (snapshot counter)
  GET /api/token/<mint>                   -> M1 + M3 + M4 for a token
  GET /api/leaderboard/rendimento         -> M3 (which memstocks paid the most in X)
  GET /api/leaderboard/lastro             -> M1 (most fragile backing)
  GET /api/creator/<addr>                 -> M4 (creator history)
  GET /api/search?q=                      -> search by name/symbol/mint
  GET /api/graph/stats                    -> D1-1 aggregates (depth histogram)
  /static and / -> static frontend (web/)
"""
import hashlib
import math
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db
import m1
import m2
import m3
import m4
import cards
import insights
import og
import onchain
import prices
import dbc_queries
import editorial

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")


class InvalidQuery(ValueError):
    """Raised when a request query parameter is malformed or out of bounds."""


def _query_int(qs, key, default, minimum=None, maximum=None):
    values = qs.get(key, [str(default)])
    if len(values) != 1:
        raise InvalidQuery(f"{key} must be provided once")
    try:
        value = int(values[0])
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidQuery(f"{key} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise InvalidQuery(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise InvalidQuery(f"{key} must be at most {maximum}")
    return value


def _query_float(qs, key, default, minimum=None, maximum=None):
    values = qs.get(key, [str(default)])
    if len(values) != 1:
        raise InvalidQuery(f"{key} must be provided once")
    try:
        value = float(values[0])
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidQuery(f"{key} must be numeric") from exc
    if not math.isfinite(value):
        raise InvalidQuery(f"{key} must be finite")
    if minimum is not None and value < minimum:
        raise InvalidQuery(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise InvalidQuery(f"{key} must be at most {maximum}")
    return value


def _auth(conn, headers):
    """Validate Authorization: Bearer <chave> against api_keys. Returns dict(tier,...) or None."""
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    key = auth[7:].strip()
    kh = hashlib.sha256(key.encode()).hexdigest()
    row = conn.execute(
        "SELECT tier, quota_monthly FROM api_keys WHERE key_hash=?", (kh,)).fetchone()
    return dict(row) if row else None


_free_hits = {}
_free_lock = threading.Lock()
FREE_RATE = 120  # req/min per visitor on the free tier (one page makes ~10 calls)


def _client_ip(handler):
    """Real visitor IP. Behind nginx/Cloudflare the peer is loopback; only then
    are the proxy headers trusted."""
    peer = handler.client_address[0]
    if peer in ("127.0.0.1", "::1") or peer.startswith("172."):
        for h in ("CF-Connecting-IP", "X-Real-IP"):
            v = (handler.headers.get(h) or "").strip()
            if v:
                return v
    return peer


def _free_allowed(ip):
    now = time.time()
    with _free_lock:
        hits = [t for t in _free_hits.get(ip, []) if now - t < 60]
        if len(hits) >= FREE_RATE:
            _free_hits[ip] = hits
            return False
        hits.append(now)
        _free_hits[ip] = hits
        return True

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}

_OG_CACHE = {}
DBC_ENABLED = os.environ.get("DBC_ENABLED", "0").lower() in {"1", "true", "yes"}
_DAS_CACHE = {}
_DAS_LOCK = threading.Lock()
_DAS_TTL = 86400


def _asset_image(asset):
    content = (asset or {}).get("content") or {}
    links = content.get("links") or {}
    image = links.get("image")
    if image:
        return image
    for item in content.get("files") or []:
        if isinstance(item, dict) and item.get("uri") and str(item.get("mime", "")).startswith("image/"):
            return item["uri"]
    return None


def _das_image(mint):
    now = time.time()
    with _DAS_LOCK:
        cached = _DAS_CACHE.get(mint)
        if cached and now - cached["ts"] < _DAS_TTL:
            return cached["image"]
    try:
        image = _asset_image(helius.get_asset(mint))
    except Exception:
        image = None
    with _DAS_LOCK:
        _DAS_CACHE[mint] = {"ts": now, "image": image}
        if len(_DAS_CACHE) > 512:
            _DAS_CACHE.pop(next(iter(_DAS_CACHE)))
    return image


class Handler(BaseHTTPRequestHandler):
    server_version = "SDB/0.1"

    def log_message(self, fmt, *args):
        pass  # silence the default log

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not fp.startswith(WEB_DIR) or not os.path.isfile(fp):
            self.send_error(404)
            return
        ext = os.path.splitext(fp)[1].lower()
        body = open(fp, "rb").read()
        cache = "no-cache" if ext == ".html" else "public, max-age=300"
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _png(self, body, mime="image/png"):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _origin(self):
        host = self.headers.get("Host", "localhost:8080").split(":", 1)[0].lower()
        proto = self.headers.get("X-Forwarded-Proto", "http")
        return f"{proto}://{host}"

    def _og_image(self, mint):
        if mint in _OG_CACHE:
            return _OG_CACHE[mint]
        conn = db.connect()
        try:
            t = m1.token_metrics(conn, mint)
            if t is None:
                return None
            r = m3.token_rewards(conn, mint)
            body = og.build_png(mint, t, r)
        finally:
            conn.close()
        if len(_OG_CACHE) > 512:
            _OG_CACHE.pop(next(iter(_OG_CACHE)))
        _OG_CACHE[mint] = body
        return body

    def _share_page(self, mint):
        conn = db.connect()
        try:
            t = m1.token_metrics(conn, mint)
            if t is None:
                return None
            r = m3.token_rewards(conn, mint)
            meta = og.share_meta(t, r)
        finally:
            conn.close()
        origin = self._origin()
        img_url = f"{origin}/og/{mint}.png"
        url = f"{origin}/t/{mint}"
        title = meta["title"]
        desc = meta["description"]
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Solana Stock Database</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{img_url}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="Solana Stock Database">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{img_url}">
<meta http-equiv="refresh" content="0; url=/#/token/{mint}">
<script>location.replace("/#/token/{mint}")</script>
</head>
<body style="font-family:sans-serif;background:#faf5ec;color:#2d2a24;padding:40px;text-align:center">
<p>Opening <a href="/#/token/{mint}" style="color:#e2562a">{title}</a>…</p>
</body>
</html>"""
        return html.encode("utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)

        m = re.match(r"^/og/([^/]+)\.png$", path)
        if m:
            body = self._og_image(m.group(1))
            if body is None:
                self.send_error(404)
            else:
                self._png(body)
            return

        m = re.match(r"^/t/([^/]+)$", path)
        if m:
            page = self._share_page(m.group(1))
            if page is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        if path == "/about":
            return self._static("/about.html")

        if path == "/docs":
            return self._static("/docs.html")

        if path == "/mcp":
            fp = os.path.join(HERE, "mcp_server.py")
            if not os.path.isfile(fp):
                self.send_error(404)
                return
            body = open(fp, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=mcp_server.py")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/api/"):
            conn = db.connect()
            try:
                self._api(conn, path, qs)
            finally:
                conn.close()
        else:
            self._static(path)

    def do_POST(self):
        u = urlparse(self.path)
        match = re.fullmatch(r"/api/creator/([^/]+)/scan", u.path)
        if not match:
            return self._send(404, {"error": "not_found"})
        conn = db.connect()
        try:
            auth = _auth(conn, self.headers)
            if not auth or auth.get("tier") != "trader":
                return self._send(401, {"error": "auth_required", "message": "Wallet scans require a Trader key."})
            qs = parse_qs(u.query)
            try:
                pages = _query_int(qs, "pages", 1, 1, 2)
            except InvalidQuery as exc:
                return self._send(400, {"error": "invalid_input", "field": "pages", "message": str(exc)})
            before_values = qs.get("before", [None])
            if len(before_values) != 1:
                return self._send(400, {"error": "invalid_input", "field": "before"})
            import creator_scan
            try:
                result = creator_scan.scan_creator(conn, match.group(1), max_pages=pages, before=before_values[0])
                return self._send(200, result)
            except ValueError as exc:
                return self._send(400, {"error": "invalid_input", "message": str(exc)})
            except Exception:
                return self._send(503, {"error": "creator_scan_unavailable", "message": "Wallet scan could not be completed."})
        finally:
            conn.close()

    def _api(self, conn, path, qs):
        try:
            if not DBC_ENABLED and path != "/api/dbc/pools" and (
                path.startswith(("/api/dbc/", "/api/meteora/", "/api/liquidity/"))
                or re.fullmatch(r"/api/token/[^/]+/dbc", path)
            ):
                off = {"status": "not_configured", "reason": "temporarily_disabled_for_presentation"}
                if path == "/api/dbc/summary":
                    off.update(available=False, freshness=None, stats={"configs": 0, "pools": 0})
                elif path == "/api/liquidity/summary":
                    off.update(totalPools=0, tvlUsd=None, tvlStatus="not_configured")
                elif path == "/api/meteora/overview":
                    off.update(counts={"configs": 0, "pools": 0})
                else:
                    off.update(available=False, total=0, pools=[], points=[])
                return self._send(200, off)
            if path not in {"/api/dbc/pools", "/api/news", "/api/creators/registry"}:
                for key, default, minimum, maximum in (
                    ("limit", 1, 1, 500),
                    ("offset", 0, 0, 100_000),
                    ("days", 1, 1, 365),
                    ("pages", 1, 1, 10),
                ):
                    if key in qs:
                        _query_int(qs, key, default, minimum, maximum)
                if "heldUsd" in qs:
                    _query_float(qs, "heldUsd", 10, 0, 1_000_000_000)
            auth = _auth(conn, self.headers)
            if not auth and not _free_allowed(_client_ip(self)):
                return self._send(429, {"error": "rate_limited",
                                        "message": "Free tier limit: 120 requests/min. A key unlocks more."})
            if not DBC_ENABLED and path != "/api/dbc/pools" and path.startswith(("/api/dbc/", "/api/meteora/", "/api/liquidity/")):
                if path == "/api/dbc/summary":
                    return self._send(200, {"available": False, "status": "not_configured", "reason": "temporarily_disabled_for_presentation", "freshness": None, "stats": {"configs": 0, "pools": 0}})
                if path == "/api/liquidity/summary":
                    return self._send(200, {"status": "not_configured", "reason": "temporarily_disabled_for_presentation", "totalPools": 0, "tvlUsd": None, "tvlStatus": "not_configured", "asOf": None, "asOfSlot": None, "source": None})
                if path == "/api/meteora/overview":
                    return self._send(200, {"status": "not_configured", "reason": "temporarily_disabled_for_presentation", "counts": {"configs": 0, "pools": 0}})
                if path == "/api/dbc/pools":
                    return self._send(200, {"status": "not_configured", "reason": "temporarily_disabled_for_presentation", "total": 0, "limit": 0, "offset": 0, "pools": []})
                if path.startswith(("/api/dbc/pool/", "/api/token/")) and path.endswith("/dbc"):
                    return self._send(200, {"status": "not_configured", "reason": "temporarily_disabled_for_presentation", "available": False, "pools": []})
                return self._send(404, {"error": "not_found"})
            if path == "/api/news":
                try:
                    limit = _query_int(qs, "limit", 30, 1, 100)
                    offset = _query_int(qs, "offset", 0, 0, 100_000)
                    return self._send(200, editorial.news(conn, limit=limit, offset=offset, asset=qs.get("asset", [None])[0]))
                except InvalidQuery:
                    return self._send(400, {"error": "invalid_input", "field": "limit_or_offset"})

            if path == "/api/creators/registry":
                try:
                    limit = _query_int(qs, "limit", 50, 1, 100)
                    offset = _query_int(qs, "offset", 0, 0, 100_000)
                    return self._send(200, editorial.creators(conn, limit=limit, offset=offset))
                except InvalidQuery:
                    return self._send(400, {"error": "invalid_input", "field": "limit_or_offset"})

            m = re.match(r"^/api/creator/([^/]+)/identity$", path)
            if m:
                item = editorial.creator(conn, m.group(1))
                return self._send(200, {"found": bool(item), "identity": item})

            if path == "/api/rpc-stats":
                stats_path = os.path.join(db.DATA_DIR, "rpc-stats.json")
                try:
                    with open(stats_path, encoding="utf-8") as f:
                        doc = json.load(f)
                except (OSError, ValueError):
                    return self._send(200, {"days": {}, "runs": []})
                days = dict(sorted(doc.get("days", {}).items())[-30:])
                return self._send(200, {"days": days, "runs": doc.get("runs", [])[-50:]})

            if path == "/api/health":
                heartbeat = os.path.join(db.DATA_DIR, "heartbeat.json")
                if not os.path.isfile(heartbeat):
                    return self._send(200, {"status": "starting", "message": "No heartbeat yet."})
                try:
                    with open(heartbeat, encoding="utf-8") as f:
                        hb = json.load(f)
                    age = time.time() - float(hb.get("ts", 0))
                    status = "stale" if age > 2250 else hb.get("status", "ok")
                    return self._send(200, {"status": status, "heartbeat": hb})
                except (OSError, ValueError, TypeError):
                    return self._send(200, {"status": "starting", "message": "Heartbeat unavailable."})

            if path == "/api/launch-readiness":
                heartbeat = os.path.join(db.DATA_DIR, "heartbeat.json")
                hb = None
                try:
                    with open(heartbeat, encoding="utf-8") as f:
                        hb = json.load(f)
                except (OSError, ValueError):
                    pass
                age = (time.time() - float(hb.get("ts", 0))) if hb else None
                health = "unavailable" if hb is None else ("stale" if age > 2250 else hb.get("status", "ok"))
                tables = {}
                for name in ("tokens", "rewards", "launches", "cycles", "dbc_collection_runs", "news_evidence", "creator_registry"):
                    try:
                        tables[name] = conn.execute(f"SELECT COUNT(*) c FROM {name}").fetchone()["c"]
                    except Exception:
                        tables[name] = None
                checks = {
                    "api": {"status": "ok"},
                    "database": {"status": "ok", "tables": tables},
                    "scheduler": {"status": health, "ageSeconds": round(age, 1) if age is not None else None},
                    "dbc": {"status": "not_configured" if not DBC_ENABLED else ("indexed" if dbc_queries.summary(conn).get("available") else "unavailable")},
                    "news": {"status": "indexed" if tables["news_evidence"] else "not_configured"},
                    "creatorRegistry": {"status": "indexed" if tables["creator_registry"] else "not_configured"},
                }
                overall = "ready" if health in {"ok", "running"} else "degraded"
                return self._send(200, {"status": overall, "checks": checks, "generatedAt": time.time()})

            if path == "/api/meteora/overview":
                if not DBC_ENABLED:
                    return self._send(200, {"status": "unavailable", "reason": "temporarily_disabled_for_presentation"})
                return self._send(200, dbc_queries.overview(conn))
            if path == "/api/dbc/summary":
                if not DBC_ENABLED:
                    return self._send(200, {"available": False, "status": "not_configured", "reason": "temporarily_disabled_for_presentation", "freshness": None, "stats": {"configs": 0, "pools": 0}})
                return self._send(200, dbc_queries.summary(conn))
            if path == "/api/liquidity/summary":
                if not DBC_ENABLED:
                    return self._send(200, {"status": "unavailable", "reason": "temporarily_disabled_for_presentation", "totalPools": 0, "tvlUsd": None, "tvlStatus": "not_configured"})
                return self._send(200, dbc_queries.liquidity_summary(conn))
            if path == "/api/dbc/pools":
                if not DBC_ENABLED:
                    return self._send(200, {"available": False, "status": "not_configured", "reason": "temporarily_disabled_for_presentation", "total": 0, "pools": []})

                try:
                    return self._send(200, dbc_queries.pools(conn, qs))
                except dbc_queries.QueryError as exc:
                    return self._send(400, {"error": "invalid_request", "message": str(exc)})
            m = re.match(r"^/api/dbc/pool/([^/]+)/history$", path)
            if m:
                if not DBC_ENABLED:
                    return self._send(200, {"status": "not_configured", "reason": "temporarily_disabled_for_presentation", "points": []})
                try:
                    limit = _query_int(qs, "limit", 100, 1, 500)
                    return self._send(200, dbc_queries.pool_history(conn, m.group(1), limit))
                except (dbc_queries.QueryError, InvalidQuery) as exc:
                    return self._send(400, {"error": "invalid_request", "message": str(exc)})
            m = re.match(r"^/api/dbc/pool/([^/]+)$", path)
            if m:
                if not DBC_ENABLED:
                    return self._send(200, {"address": m.group(1), "status": "not_configured", "reason": "temporarily_disabled_for_presentation"})
                try:
                    item = dbc_queries.pool_detail(conn, m.group(1))
                except dbc_queries.QueryError:
                    return self._send(400, {"error": "invalid_pool_address"})
                if item is None:
                    return self._send(404, {"error": "not_found"})
                return self._send(200, item)

            m = re.match(r"^/api/token/([^/]+)/dbc$", path)
            if m:
                if not DBC_ENABLED:
                    return self._send(200, {"mint": m.group(1), "available": False, "status": "not_configured", "reason": "temporarily_disabled_for_presentation", "pools": []})
                try:
                    limit = _query_int(qs, "limit", 20, 1, 100)
                    return self._send(200, dbc_queries.token_pools(conn, m.group(1), limit=limit))
                except dbc_queries.QueryError as exc:
                    return self._send(400, {"error": "invalid_request", "message": str(exc)})
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})

            m = re.match(r"^/api/token/([^/]+)/history$", path)
            if m:
                mint = m.group(1)
                try:
                    limit = _query_int(qs, "limit", 120, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                rows = conn.execute(
                    """SELECT captured_at, price_usd, market_cap_usd, fdv_usd,
                              volume_24h_usd, status, graduation_progress,
                              peak_market_cap_usd, transfer_fee_bps
                       FROM snapshots WHERE mint=?
                       ORDER BY captured_at DESC LIMIT ?""",
                    (mint, limit),
                ).fetchall()
                return self._send(200, {"mint": mint, "points": [dict(r) for r in reversed(rows)]})

            m = re.match(r"^/api/token/([^/]+)$", path)
            if m:
                mint = m.group(1)
                metrics = m1.token_metrics(conn, mint)
                if metrics is None:
                    return self._send(404, {"found": False, "mint": mint})
                rewards = m3.token_rewards(conn, mint)
                creator = m4.creator_stats(conn, metrics["creator"]) if metrics.get("creator") else None
                audit = None
                portfolio = None
                if metrics.get("creator"):
                    if creator:
                        creator["x"] = insights.creator_x(conn, metrics["creator"])
                    audit = m4.token_changes(conn, mint)
                    portfolio = m4.creator_portfolio(conn, metrics["creator"], exclude_mint=mint)
                holders = conn.execute(
                    "SELECT owner, amount_ui, pct FROM holders WHERE mint=? ORDER BY pct DESC LIMIT 20",
                    (mint,)).fetchall()
                top10 = conn.execute(
                    "SELECT holder_top10_share FROM tokens WHERE mint=?", (mint,)).fetchone()
                events = conn.execute(
                    "SELECT kind, COUNT(*) c FROM token_events WHERE mint=? GROUP BY kind",
                    (mint,)).fetchall()
                pool = conn.execute(
                    "SELECT pool, program FROM pools WHERE mint=?", (mint,)).fetchone()
                burn = conn.execute(
                    "SELECT SUM(amount_ui) total_ui, COUNT(*) c FROM burns WHERE mint=?",
                    (mint,)).fetchone()
                decomposition = m2.decomposition(conn, mint, window=qs.get("window", ["7"])[0])
                price = (metrics.get("market") or {}).get("priceUsd")
                onchain_data = {
                    "holders": [dict(h) for h in holders],
                    "holderTop10Share": (top10["holder_top10_share"] if top10 else None),
                    "events": [dict(e) for e in events],
                    "pool": dict(pool) if pool else None,
                    "burn": {
                        "totalBurnedUi": burn["total_ui"],
                        "burnEvents": burn["c"],
                        "burnValueUsd": round((burn["total_ui"] or 0) * price, 2)
                            if (burn["total_ui"] and price) else None,
                    },
                }
                return self._send(200, {"found": True, "token": metrics,
                                        "rewards": rewards, "creator": creator,
                                        "audit": audit, "portfolio": portfolio,
                                        "onchain": onchain_data,
                                        "decomposition": decomposition})

            m = re.match(r"^/api/token/([^/]+)/holders$", path)
            if m:
                mint = m.group(1)
                rows = conn.execute(
                    "SELECT owner, amount_ui, pct FROM holders WHERE mint=? ORDER BY pct DESC LIMIT 50",
                    (mint,)).fetchall()
                return self._send(200, {"mint": mint, "holders": [dict(r) for r in rows]})

            m = re.match(r"^/api/token/([^/]+)/refresh$", path)
            if m:
                mint = m.group(1)
                if not auth or auth["tier"] not in ("starter", "trader"):
                    return self._send(401, {
                        "error": "auth_required",
                        "message": "Real-time refresh requires a Starter or Trader key."})
                if not onchain.enrich_token(conn, mint):
                    return self._send(404, {"found": False, "mint": mint})
                return self._send(200, {"found": True,
                                        "token": m1.token_metrics(conn, mint),
                                        "refreshed": True})

            m = re.match(r"^/api/token/([^/]+)/fee-simulation$", path)
            if m:
                mint = m.group(1)
                metrics = m1.token_metrics(conn, mint)
                if metrics is None:
                    return self._send(404, {"found": False, "mint": mint})
                try:
                    held = _query_float(qs, "heldUsd", 10, 0, 1_000_000_000)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "heldUsd", "message": str(exc)})
                market = metrics.get("market") or {}
                simulation = m3.fee_distribution_simulation(
                    held, market.get("volume24hUsd"), market.get("marketCapUsd"),
                    metrics.get("stackedTransferTaxBps"), metrics.get("terminalPriceUsd"))
                return self._send(200, {"found": True, "mint": mint,
                                        "heldUsd": held, "terminal": metrics.get("terminal"),
                                        "simulation": simulation})

            if path == "/api/stats":
                # Use the compact cycle ledger for homepage stats. Counting 28M+
                # historical snapshots on every request blocks the public API.
                first = conn.execute("SELECT MIN(captured_at) m FROM cycles").fetchone()["m"]
                n_snap = conn.execute("SELECT COUNT(*) c FROM cycles").fetchone()["c"]
                n_tok = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"]
                n_rew = conn.execute("SELECT COUNT(*) c FROM rewards").fetchone()["c"]
                n_lau = conn.execute("SELECT COUNT(*) c FROM launches").fetchone()["c"]
                n_creators = conn.execute("SELECT COUNT(*) c FROM (SELECT creator FROM tokens WHERE creator IS NOT NULL GROUP BY creator)").fetchone()["c"]
                return self._send(200, {
                    "tokenCount": n_tok, "snapshotCycles": n_snap,
                    "rewardCoins": n_rew, "launches": n_lau,
                    "creators": n_creators, "firstSnapshotAt": first,
                })

            if path == "/api/cards":
                range_key = qs.get("range", ["ALL"])[0]
                sort = qs.get("sort", ["mc"])[0]
                try:
                    limit = _query_int(qs, "limit", 30, 1, 500)
                    offset = _query_int(qs, "offset", 0, 0, 100_000)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit_or_offset", "message": str(exc)})
                return self._send(200, cards.cards(conn, range_key, limit, offset, sort))

            m = re.match(r"^/api/asset/([^/]+)/image$", path)
            if m:
                image = _das_image(m.group(1))
                if image:
                    self.send_response(302)
                    self.send_header("Location", image)
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    return
                return self._send(404, {"mint": m.group(1), "image": None})

            if path == "/api/quote-market-caps":
                quote_caps = insights.quote_market_caps(conn)
                stock_signals = {x["symbol"]: {"priceUsd": x.get("priceUsd"), "sharePct": x.get("sharePct"), "tokenCount": x.get("tokenCount"), "ticker": x.get("ticker"), "name": x.get("name")} for x in prices.ticker(conn)}
                for symbol, data in quote_caps.items():
                    ticker = prices.TICKERS.get(symbol, (None, None))[0]
                    data["stock"] = stock_signals.get(symbol, {"ticker": ticker, "priceUsd": None, "sharePct": None, "tokenCount": None})
                return self._send(200, {"quotes": quote_caps})

            if path == "/api/assets":
                return self._send(200, {"assets": insights.assets(conn)})

            m = re.match(r"^/api/assets/([^/]+)/history$", path)
            if m:
                symbol = m.group(1).upper()
                try:
                    limit = _query_int(qs, "limit", 120, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                rows = conn.execute(
                    """SELECT terminal, captured_at, token_count, market_cap_usd,
                              volume_24h_usd, live_count, graduated_count, creator_count
                       FROM asset_snapshots WHERE terminal=?
                       ORDER BY captured_at DESC LIMIT ?""",
                    (symbol, limit),
                ).fetchall()
                return self._send(200, {"terminal": symbol, "points": [dict(r) for r in reversed(rows)], "source": "asset_snapshots"})

            m = re.match(r"^/api/assets/([^/]+)$", path)
            if m:
                try:
                    limit = _query_int(qs, "limit", 200, 1, 500)
                    offset = _query_int(qs, "offset", 0, 0, 100_000)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit_or_offset", "message": str(exc)})
                d = insights.asset_detail(conn, m.group(1), limit=limit, offset=offset)
                if d is None:
                    return self._send(404, {"found": False})
                return self._send(200, {"found": True, "asset": d})

            if path == "/api/survival":
                return self._send(200, insights.survival(conn))

            if path == "/api/ticker":
                return self._send(200, {"ticker": prices.ticker(conn)})

            if path == "/api/attention":
                try:
                    days = _query_int(qs, "days", 7, 1, 365)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "days", "message": str(exc)})
                return self._send(200, insights.attention(conn, days))

            if path == "/api/leaderboard/rendimento":
                cat = qs.get("category", ["xstock"])[0] or None
                try:
                    limit = _query_int(qs, "limit", 50, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                return self._send(200, {"leaderboard": m3.leaderboard_rendimento(conn, category=cat, limit=limit)})

            if path == "/api/leaderboard/lastro":
                try:
                    limit = _query_int(qs, "limit", 50, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                return self._send(200, {"leaderboard": m1.leaderboard_lastro(conn, limit=limit)})

            if path == "/api/leaderboard/creators":
                try:
                    limit = _query_int(qs, "limit", 50, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                leaderboard = m4.top_creators(conn, limit=limit, min_launches=2)
                if qs.get("watch", ["0"])[0] == "1":
                    import creator_scan
                    creator_scan.add_watchlist(conn, [x["creator"] for x in leaderboard], source="leaderboard", priority=limit)
                return self._send(200, {"leaderboard": leaderboard})

            if path == "/api/creators/watchlist":
                rows = conn.execute("SELECT * FROM creator_watchlist WHERE enabled=1 ORDER BY priority DESC, creator LIMIT 200").fetchall()
                return self._send(200, {"watchlist": [dict(r) for r in rows]})

            if path == "/api/leaderboard/early":
                try:
                    limit = _query_int(qs, "limit", 50, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                return self._send(200, {"leaderboard": m4.early_wallets(conn, limit=limit)})


            m = re.match(r"^/api/creator/([^/]+)/tokens$", path)
            if m:
                addr = m.group(1)
                try:
                    limit = _query_int(qs, "limit", 60, 1, 100)
                    offset = _query_int(qs, "offset", 0, 0, 100_000)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit_or_offset", "message": str(exc)})
                total = conn.execute("SELECT COUNT(*) c FROM launches WHERE creator=?", (addr,)).fetchone()["c"]
                if total == 0:
                    return self._send(404, {"found": False, "creator": addr})
                return self._send(200, {"found": True, "creator": addr,
                                        "tokens": m4.creator_portfolio(conn, addr, limit=limit, offset=offset),
                                        "total": total, "limit": limit, "offset": offset})

            m = re.match(r"^/api/creator/([^/]+)/scan-runs$", path)
            if m:
                addr = m.group(1)
                rows = conn.execute("SELECT * FROM creator_scan_runs WHERE creator=? ORDER BY id DESC LIMIT 20", (addr,)).fetchall()
                return self._send(200, {"creator": addr, "runs": [dict(r) for r in rows]})

            m = re.match(r"^/api/creator/([^/]+)/history$", path)
            if m:
                addr = m.group(1)
                try:
                    limit = _query_int(qs, "limit", 120, 1, 500)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                rows = conn.execute(
                    """SELECT s.captured_at,
                              SUM(s.market_cap_usd) AS market_cap_usd,
                              SUM(s.volume_24h_usd) AS volume_24h_usd,
                              COUNT(DISTINCT s.mint) AS live_tokens,
                              COUNT(DISTINCT CASE WHEN s.status='graduated' THEN s.mint END) AS graduated_tokens
                       FROM snapshots s JOIN tokens t ON t.mint=s.mint
                       WHERE t.creator=?
                       GROUP BY s.captured_at ORDER BY s.captured_at ASC LIMIT ?""",
                    (addr, limit),
                ).fetchall()
                return self._send(200, {"creator": addr, "points": [dict(r) for r in rows]})

            m = re.match(r"^/api/creator/([^/]+)$", path)
            if m:
                addr = m.group(1)
                s = m4.creator_stats(conn, addr)
                s["x"] = insights.creator_x(conn, addr)
                return self._send(200, {"creator": s})

            if path == "/api/search":
                q = (qs.get("q", [""])[0] or "").strip()
                try:
                    limit = _query_int(qs, "limit", 30, 1, 100)
                except InvalidQuery as exc:
                    return self._send(400, {"error": "invalid_input", "field": "limit", "message": str(exc)})
                if not q:
                    return self._send(200, {"results": [], "assets": []})
                like = f"%{q}%"
                rows = conn.execute(
                    """SELECT mint, symbol, name, image_url, market_cap_usd, depth, terminal_symbol,
                              terminal_category, status
                       FROM tokens
                       WHERE symbol LIKE ? OR name LIKE ? OR mint LIKE ?
                       ORDER BY market_cap_usd DESC NULLS LAST LIMIT ?""",
                    (like, like, like, limit),
                ).fetchall()
                assets = conn.execute(
                    """SELECT terminal_symbol, terminal_category, terminal_category_label, COUNT(*) c
                       FROM tokens WHERE terminal_symbol LIKE ?
                       GROUP BY terminal_symbol, terminal_category, terminal_category_label
                       ORDER BY c DESC LIMIT 5""",
                    (like,),
                ).fetchall()
                return self._send(200, {"results": [dict(r) for r in rows],
                                        "assets": [dict(a) for a in assets]})

            if path == "/api/graph/stats":
                hist = conn.execute(
                    "SELECT depth, COUNT(*) c FROM tokens GROUP BY depth ORDER BY depth"
                ).fetchall()
                cat = conn.execute(
                    "SELECT terminal_category c, COUNT(*) n FROM tokens GROUP BY terminal_category ORDER BY n DESC"
                ).fetchall()
                chained = conn.execute(
                    "SELECT COUNT(*) c FROM tokens WHERE depth > 1").fetchone()["c"]
                total = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"]
                return self._send(200, {
                    "total": total,
                    "depthHistogram": {r["depth"]: r["c"] for r in hist},
                    "terminalCategories": {r["c"]: r["n"] for r in cat},
                    "chainedCount": chained,
                })

            return self._send(404, {"error": "not_found", "path": path})
        except InvalidQuery as e:
            return self._send(400, {"error": "invalid_input", "message": str(e)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": "internal"})


def main(port=8080):
    if not db.is_split():
        db.init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SDB API listening on http://localhost:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8080)
