"""SDB – gerador de relatório (pulse de 15 min) para posts automatizados.

Lê só do SQLite (nunca da API). Gera um digest markdown curto com o que
mudou no intervalo, pronto para virar post (X API) e alimentar a
newsletter diária/semanal. As integrações de postagem ficam no BACKLOG.

Uso: python report.py [minutos]
"""
import os
import sys
import time

import db

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "data", "reports")


def _cutoff_iso(minutes):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(time.time() - minutes * 60))


def _iso_ok(s):
    return isinstance(s, str) and len(s) >= 19 and s[4] == "-" and s[10] == "T"


def pulse(conn, minutes=15):
    cutoff = _cutoff_iso(minutes)
    out = []
    out.append(f"# SDB · pulse {minutes}min · {time.strftime('%H:%MZ', time.gmtime())}")

    # 1. novos lançamentos no intervalo
    new_launches = conn.execute(
        "SELECT COUNT(*) c FROM launches WHERE created_at >= ?", (cutoff,)
    ).fetchone()["c"]
    new_by_terminal = conn.execute(
        """SELECT COALESCE(t2.terminal_symbol, l.quote_symbol) term, COUNT(*) c
           FROM launches l LEFT JOIN tokens t2 ON t2.mint = l.quote_mint
           WHERE l.created_at >= ? GROUP BY term ORDER BY c DESC LIMIT 5""",
        (cutoff,),
    ).fetchall()
    if new_launches:
        tops = " · ".join(f"{r['term']} {r['c']}" for r in new_by_terminal)
        out.append(f"\n**Novos memstocks ({minutes}min): {new_launches}**\n> {tops}")

    # 2. top movers (variação 24h) – sem recomendar, só fato
    # top movers: filtra micro-caps (mcap > $10k), dedupe por símbolo, cap de exibição
    rows = conn.execute(
        """SELECT symbol, terminal_symbol, price_change_24h, market_cap_usd
           FROM tokens WHERE price_change_24h IS NOT NULL
           AND market_cap_usd > 10000
           ORDER BY market_cap_usd DESC LIMIT 60"""
    ).fetchall()
    seen = {}
    for r in rows:
        seen.setdefault(r["symbol"], r)  # mantém o de maior mcap (vem primeiro)
    movers = sorted(seen.values(), key=lambda x: -abs(x["price_change_24h"]))[:5]
    if movers:
        lines = []
        for r in movers:
            d = r["price_change_24h"]
            arrow = "↑" if d >= 0 else "↓"
            mag = f"{abs(d):.0f}%" if abs(d) < 1000 else ">1000%"
            lines.append(f"{r['symbol']} ({r['terminal_symbol']}) {arrow}{mag}")
        out.append("\n**Top movers 24h**\n> " + " · ".join(lines))

    # 3. atenção por ativo terminal (launches acumulados na janela)
    attn = conn.execute(
        """SELECT COALESCE(t2.terminal_symbol, l.quote_symbol) term, COUNT(*) c
           FROM launches l LEFT JOIN tokens t2 ON t2.mint = l.quote_mint
           WHERE l.created_at >= ? GROUP BY term ORDER BY c DESC LIMIT 6""",
        (cutoff,),
    ).fetchall()
    if attn:
        out.append("\n**Atenção por ativo (lançamentos)**\n> "
                   + " · ".join(f"{r['term']} {r['c']}" for r in attn))

    # 4. rendimento em ação (maiores reward coins, vitalício)
    yield_rows = conn.execute(
        """SELECT r.quote_symbol, SUM(r.distributed_tokens) y, COUNT(*) coins
           FROM rewards r WHERE r.distributed_tokens > 0
           GROUP BY r.quote_symbol ORDER BY y DESC LIMIT 5"""
    ).fetchall()
    if yield_rows:
        out.append("\n**Maiores pagadores (rendimento em ação, vitalício)**\n> "
                   + " · ".join(f"{r['quote_symbol']} {r['y']:,.0f}" for r in yield_rows))

    # 5. eventos on-chain recentes (dev actions)
    ev = conn.execute(
        """SELECT COUNT(*) c, kind FROM token_events GROUP BY kind ORDER BY c DESC"""
    ).fetchall()
    if ev:
        out.append("\n**Eventos on-chain (dev)**\n> "
                   + " · ".join(f"{r['kind']} {r['c']}" for r in ev))

    return "\n".join(out)


def main():
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    conn = db.connect()
    db.init_db(conn)
    text = pulse(conn, minutes)
    os.makedirs(REPORTS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(REPORTS, f"pulse-{ts}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    conn.close()
    print(text)
    print(f"\n[salvo em {path}]")


if __name__ == "__main__":
    main()
