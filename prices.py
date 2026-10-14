"""SDB: USD price of underlying assets (xStocks -> real stock).

Source: Yahoo Finance (chart endpoint, no key). Not from the StonkFun API.
Cached in `terminal_prices` so serving never depends on the source.
"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# terminal_symbol -> (Yahoo ticker, display name)
TICKERS = {
    "SPYX": ("SPY", "S&P 500"),
    "NVDAX": ("NVDA", "NVIDIA"),
    "APPLX": ("AAPL", "Apple"),
    "HOODX": ("HOOD", "Robinhood"),
    "GLDX": ("GLD", "Gold"),
    "MCDX": ("MCD", "McDonald's"),
    "TSLAX": ("TSLA", "Tesla"),
    "QQQX": ("QQQ", "Nasdaq 100"),
    "MSFTX": ("MSFT", "Microsoft"),
    "GOOGLX": ("GOOGL", "Alphabet"),
    "GMEX": ("GME", "GameStop"),
    "METAX": ("META", "Meta"),
    "COINX": ("COIN", "Coinbase"),
    "PLTRX": ("PLTR", "Palantir"),
    "AMZNX": ("AMZN", "Amazon"),
    "KOX": ("KO", "Coca-Cola"),
    "MSTRX": ("MSTR", "MicroStrategy"),
    "BRKX": ("BRK-B", "Berkshire Hathaway"),
    "INTCX": ("INTC", "Intel"),
}

_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d&range=1d"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_MAX_AGE = 900  # 15 min


def _fetch_one(ticker):
    try:
        req = urllib.request.Request(_YAHOO.format(ticker), headers=_UA)
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        meta = d["chart"]["result"][0]["meta"]
        p = meta.get("regularMarketPrice")
        return (ticker, float(p)) if p else (ticker, None)
    except Exception:
        return (ticker, None)


def _fetch_many(tickers):
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, p in ex.map(_fetch_one, tickers):
            if p is not None:
                out[t] = p
    return out


def _fresh(row):
    if not row or not row["captured_at"]:
        return False
    try:
        ts = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() < _MAX_AGE
    except (ValueError, TypeError):
        return False


def get_prices(conn, symbols):
    """symbols: list of terminal_symbol (e.g. NVDAX). Returns {symbol: price_usd}.

    Uses the `terminal_prices` cache; fetches missing/stale entries from Yahoo.
    """
    tickers = {s: TICKERS[s][0] for s in symbols if s in TICKERS}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fresh = {}
    stale = {}
    for s, t in tickers.items():
        row = conn.execute(
            "SELECT price_usd, captured_at FROM terminal_prices WHERE symbol=?", (s,)
        ).fetchone()
        if _fresh(row):
            fresh[s] = row["price_usd"]
        else:
            stale[s] = t

    fetched = _fetch_many(set(stale.values())) if stale else {}
    by_ticker = {t: s for s, t in stale.items()}

    prices = dict(fresh)
    for t, p in fetched.items():
        s = by_ticker[t]
        prices[s] = p
        conn.execute(
            "INSERT INTO terminal_prices (symbol, ticker, price_usd, captured_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET price_usd=excluded.price_usd, "
            "ticker=excluded.ticker, captured_at=excluded.captured_at",
            (s, t, p, now),
        )
    conn.commit()

    # fallback: use the last cached value even if stale
    for s in tickers:
        if s not in prices:
            row = conn.execute(
                "SELECT price_usd FROM terminal_prices WHERE symbol=?", (s,)
            ).fetchone()
            if row and row["price_usd"] is not None:
                prices[s] = row["price_usd"]
    return prices


def ticker(conn):
    """Home feed: underlying stocks ordered by share, with price and %."""
    total = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"]
    rows = conn.execute(
        """SELECT terminal_symbol, COUNT(*) c
           FROM tokens WHERE terminal_symbol IS NOT NULL
           GROUP BY terminal_symbol"""
    ).fetchall()
    shares = {r["terminal_symbol"]: r["c"] for r in rows}

    symbols = [s for s in TICKERS if shares.get(s)]
    prices = get_prices(conn, symbols)

    out = []
    for s in symbols:
        ticker_sym, name = TICKERS[s]
        c = shares[s]
        out.append({
            "symbol": s,
            "ticker": ticker_sym,
            "name": name,
            "priceUsd": prices.get(s),
            "tokenCount": c,
            "sharePct": round(c / total * 100, 2) if total else 0,
        })
    out.sort(key=lambda x: -x["tokenCount"])
    return out
