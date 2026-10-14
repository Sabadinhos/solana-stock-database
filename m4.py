"""SDB — M4 Histórico de Criador (núcleo).

Reputação por carteira criadora, sem indexação on-chain: cruza `launches` (todos os
lançamentos, inclusive mortos) com `tokens` (vivos, com status e pico).
"""
import statistics
from datetime import datetime


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def creator_stats(conn, creator):
    lau = conn.execute(
        "SELECT * FROM launches WHERE creator=? ORDER BY created_at", (creator,)
    ).fetchall()
    live = conn.execute(
        "SELECT * FROM tokens WHERE creator=?", (creator,)
    ).fetchall()
    volume_token = max(live, key=lambda t: (t["volume_24h_usd"] or 0), default=None)

    n_launches = len(lau)
    n_live = len(live)
    graduated = [t for t in live if t["status"] == "graduated"]
    peaks = [t["peak_market_cap_usd"] for t in live if t["peak_market_cap_usd"]]

    # tempo até graduar (proxy de "tempo até o pico")
    times_to_grad = []
    for t in graduated:
        c = _parse(t["created_at"])
        g = _parse(t["graduated_at"])
        if c and g and g >= c:  # graduated_at anterior a created_at = dado inconsistente, ignora
            times_to_grad.append((g - c).total_seconds() / 60.0)

    # intervalo entre lançamentos (min)
    created = [c for c in (_parse(l["created_at"]) for l in lau) if c]
    intervals = []
    for a, b in zip(created, created[1:]):
        intervals.append((b - a).total_seconds() / 3600.0)  # horas

    return {
        "creator": creator,
        "launches": n_launches,
        "live": n_live,
        "graduated": len(graduated),
        "dead": max(0, n_launches - n_live),
        "medianPeakMarketCapUsd": statistics.median(peaks) if peaks else None,
        "maxPeakMarketCapUsd": max(peaks) if peaks else None,
        "medianTimeToGraduationMin": statistics.median(times_to_grad) if times_to_grad else None,
        "medianLaunchIntervalH": statistics.median(intervals) if intervals else None,
        "firstLaunchAt": lau[0]["created_at"] if lau else None,
        "lastLaunchAt": lau[-1]["created_at"] if lau else None,
        "topVolumeToken": {
            "mint": volume_token["mint"],
            "symbol": volume_token["symbol"],
            "name": volume_token["name"],
            "volume24hUsd": volume_token["volume_24h_usd"],
            "image_url": volume_token["image_url"],
            "rewardAsset": volume_token["terminal_symbol"],
        } if volume_token else None,
    }


def top_creators(conn, limit=50, min_launches=1):
    """Ranking de criadores reincidentes."""
    rows = conn.execute(
        """SELECT creator, COUNT(*) c FROM launches
           GROUP BY creator HAVING c >= ? ORDER BY c DESC LIMIT ?""",
        (min_launches, limit),
    ).fetchall()
    out = []
    for r in rows:
        s = creator_stats(conn, r["creator"])
        s["launchCount"] = r["c"]
        out.append(s)
    return out


def early_wallets(conn, limit=50):
    """Ranking das carteiras mais antigas (criadores), com o status agregado da posição.

    "Early" = data do primeiro lançamento (quem entrou cedo na plataforma). A posição é
    agregada dos tokens vivos da carteira: quanto deployou no lançamento, quanto vale
    agora, quanto vale no pico, e o placar de graduados vs mortos.
    """
    rows = conn.execute(
        """SELECT creator,
                  MIN(created_at) AS first_launch,
                  COUNT(DISTINCT mint) AS tokens,
                  COALESCE(SUM(start_market_cap_usd), 0) AS deployed
           FROM launches
           WHERE creator IS NOT NULL
           GROUP BY creator
           ORDER BY first_launch ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    out = []
    for r in rows:
        agg = conn.execute(
            """SELECT COUNT(*) live,
                      SUM(status='graduated') graduated,
                      COALESCE(SUM(market_cap_usd), 0) live_value,
                      COALESCE(SUM(peak_market_cap_usd), 0) peak_value
               FROM tokens WHERE creator=?""",
            (r["creator"],),
        ).fetchone()
        live = agg["live"] or 0
        grad = agg["graduated"] or 0
        live_value = agg["live_value"] or 0
        peak_value = agg["peak_value"] or 0
        dead = max(0, r["tokens"] - live)
        drawdown = ((peak_value - live_value) / peak_value) if peak_value else None
        out.append({
            "creator": r["creator"],
            "firstLaunchAt": r["first_launch"],
            "tokens": r["tokens"],
            "deployed": r["deployed"],
            "liveValue": live_value,
            "peakValue": peak_value,
            "drawdown": drawdown,
            "graduated": grad,
            "dead": dead,
        })
    return out


def token_changes(conn, mint):
    """Diff launch -> estado atual de UM token: o que o dev alterou nele.

    Compara o registro de lançamento (`launches`) com o estado vivo (`tokens`).
    Captura fee, quote e mode quando mudaram, além da trajetória de status.
    """
    t = conn.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
    if t is None:
        return None
    l = conn.execute("SELECT * FROM launches WHERE mint=?", (mint,)).fetchone()

    changes = []
    if l:
        if l["transfer_fee_bps"] is not None and t["transfer_fee_bps"] is not None \
                and l["transfer_fee_bps"] != t["transfer_fee_bps"]:
            changes.append({
                "field": "transferFee", "label": "Transfer fee",
                "fromBps": l["transfer_fee_bps"], "toBps": t["transfer_fee_bps"],
            })
        if l["quote_symbol"] and t["quote_symbol"] and l["quote_symbol"] != t["quote_symbol"]:
            changes.append({
                "field": "quote", "label": "Quote",
                "from": l["quote_symbol"], "to": t["quote_symbol"],
            })
        if l["mode"] and t["mode"] and l["mode"] != t["mode"]:
            changes.append({
                "field": "mode", "label": "Mode",
                "from": l["mode"], "to": t["mode"],
            })

    return {
        "mint": mint,
        "launch": {
            "launchpad": l["launchpad"] if l else None,
            "mode": l["mode"] if l else None,
            "transferFeeBps": l["transfer_fee_bps"] if l else None,
            "startMarketCapUsd": l["start_market_cap_usd"] if l else None,
            "targetMarketCapUsd": l["target_market_cap_usd"] if l else None,
            "createdAt": l["created_at"] if l else None,
        } if l else None,
        "current": {
            "transferFeeBps": t["transfer_fee_bps"],
            "quoteSymbol": t["quote_symbol"],
            "mode": t["mode"],
            "status": t["status"],
            "marketCapUsd": t["market_cap_usd"],
            "peakMarketCapUsd": t["peak_market_cap_usd"],
            "graduatedAt": t["graduated_at"],
        },
        "changes": changes,
    }


def creator_portfolio(conn, creator, exclude_mint=None, limit=60, offset=0):
    """Todos os lançamentos de uma carteira (vivos e mortos), excluindo um mint.

    `launches` é a fonte de verdade (inclui mortos); `tokens` dá o estado atual.
    """
    rows = conn.execute(
        """SELECT l.mint, l.symbol AS l_symbol, l.name, l.created_at,
                  l.transfer_fee_bps AS launch_fee, l.launchpad,
                  t.symbol, t.status, t.market_cap_usd, t.terminal_symbol, t.image_url,
                  t.transfer_fee_bps AS cur_fee, t.graduated_at
           FROM launches l LEFT JOIN tokens t ON t.mint = l.mint
           WHERE l.creator=? ORDER BY l.created_at DESC LIMIT ? OFFSET ?""",
        (creator, limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        if r["mint"] == exclude_mint:
            continue
        out.append({
            "mint": r["mint"],
            "symbol": r["symbol"] or r["l_symbol"],
            "name": r["name"],
            "status": r["status"] or "dead",
            "marketCapUsd": r["market_cap_usd"],
            "market_cap_usd": r["market_cap_usd"],
            "terminal": r["terminal_symbol"],
            "terminal_symbol": r["terminal_symbol"],
            "image_url": r["image_url"],
            "launchpad": r["launchpad"],
            "launchFeeBps": r["launch_fee"],
            "currentFeeBps": r["cur_fee"],
            "feeChanged": (r["launch_fee"] is not None and r["cur_fee"] is not None
                           and r["launch_fee"] != r["cur_fee"]),
            "createdAt": r["created_at"],
            "graduatedAt": r["graduated_at"],
        })
    known = {item["mint"] for item in out}
    evidence = conn.execute(
        """SELECT e.mint, e.first_seen_at, e.signature, e.slot, e.evidence_type,
                  t.symbol, t.name, t.status, t.market_cap_usd, t.terminal_symbol, t.image_url
           FROM creator_token_evidence e LEFT JOIN tokens t ON t.mint=e.mint
           WHERE e.creator=? ORDER BY e.first_seen_at DESC""",
        (creator,),
    ).fetchall()
    for r in evidence:
        if r["mint"] in known:
            continue
        out.append({
            "mint": r["mint"], "symbol": r["symbol"] or r["mint"][:8],
            "name": r["name"], "status": r["status"] or "unindexed",
            "marketCapUsd": r["market_cap_usd"], "market_cap_usd": r["market_cap_usd"],
            "terminal": r["terminal_symbol"], "terminal_symbol": r["terminal_symbol"],
            "image_url": r["image_url"], "createdAt": r["first_seen_at"],
            "verification": {"type": r["evidence_type"], "signature": r["signature"], "slot": r["slot"]},
        })
    return out
