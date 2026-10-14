"""M2: separate token USD movement from terminal-asset movement."""
from datetime import datetime, timedelta, timezone


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def decomposition(conn, mint, window=7, tolerance_minutes=45):
    try:
        days = min(max(int(window), 1), 90)
    except (TypeError, ValueError):
        days = 7
    token = conn.execute(
        "SELECT terminal_symbol FROM tokens WHERE mint=?", (mint,)
    ).fetchone()
    if not token or not token["terminal_symbol"]:
        return None
    terminal = token["terminal_symbol"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshots = conn.execute(
        "SELECT captured_at, price_usd FROM snapshots "
        "WHERE mint=? AND captured_at>=? AND price_usd>0 "
        "ORDER BY captured_at ASC LIMIT 1000", (mint, cutoff)
    ).fetchall()
    assets = conn.execute(
        "SELECT captured_at, price_usd, conf, publish_time FROM asset_prices "
        "WHERE terminal=? AND captured_at>=? AND price_usd>0 "
        "ORDER BY captured_at ASC LIMIT 1000", (terminal, cutoff)
    ).fetchall()
    if len(snapshots) < 2 or len(assets) < 2:
        return None
    tolerance = timedelta(minutes=tolerance_minutes)
    aligned = []
    for snap in snapshots:
        st = _parse_time(snap["captured_at"])
        if not st:
            continue
        candidates = [(row, _parse_time(row["captured_at"])) for row in assets]
        candidates = [(row, at) for row, at in candidates if at]
        if not candidates:
            continue
        nearest, at = min(candidates, key=lambda item: abs(item[1] - st))
        if abs(at - st) <= tolerance:
            aligned.append((st, float(snap["price_usd"]), float(nearest["price_usd"])))
    if len(aligned) < 2:
        return None
    first, last = aligned[0], aligned[-1]
    token_return = last[1] / first[1] - 1
    terminal_return = last[2] / first[2] - 1
    relative_return = (1 + token_return) / (1 + terminal_return) - 1 if terminal_return > -1 else None
    latest_asset = assets[-1]
    publish = latest_asset["publish_time"]
    stale = bool(publish and datetime.now(timezone.utc).timestamp() - int(publish) > 15 * 60)
    return {
        "status": "stale" if stale else "ok",
        "terminal": terminal,
        "windowDays": days,
        "points": len(aligned),
        "tokenReturnUsd": token_return,
        "terminalReturn": terminal_return,
        "relativeReturn": relative_return,
        "terminalPriceUsd": last[2],
        "terminalPublishTime": publish,
        "terminalStale": stale,
    }


def _test_decomposition():
    assert _parse_time("2026-01-01T00:00:00Z") is not None
    assert _parse_time("bad") is None


if __name__ == "__main__":
    _test_decomposition()
    print("m2 self-test passed")
