import re
from pathlib import Path

ROOT = Path(__file__).parent
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
PY = (ROOT / "m4.py").read_text(encoding="utf-8")

checks = {
    "shared sort helper": "function makeSortable" in JS and 'aria-sort' in JS,
    "creator sortable head": 'data-sort="wallet"' in JS and 'data-sort="peak"' in JS,
    "portfolio sortable head": "modal-token-head" in JS and 'data-sort="age"' in JS,
    "live sortable heads": "live-head" in JS and 'data-sort="value"' in JS,
    "assets sortable head": "asset-head" in JS and 'data-sort="depth"' in JS,
    "momentum sortable heads": 'id="att-head"' in JS and 'id="surv-head"' in JS,
    "token icons": "function tokenIcon" in JS and "decoding=\"async\"" in JS,
    "verification safely false": "verified: false" in JS and "verifiedBadge(false)" in JS,
    "verified filter": "only-verified" in JS and "verified-filter" in CSS,
    "portfolio image API": '"imageUrl": r["image_url"]' in PY,
    "nav centered": "max-width: 1280px; margin-inline: auto" in CSS,
    "modal columns": "grid-template-columns: 22px 1fr 1.2fr auto 90px 60px" in CSS,
    "no double class attrs": not re.search(r'class="[^"]*"[^>]*class="', JS),
    "css braces balanced": CSS.count("{") == CSS.count("}"),
    "no css corruption": '\n"""' not in CSS and not re.search(r'^# ', CSS, re.M),
    "dbc route and nav": 'renderDbc()' in JS and 'startsWith("#/meteora-dbc")' in JS,
    "dbc passport fields": "migrationQuoteThreshold" in JS and "Permanent liquidity" in JS,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(("PASS" if ok else "FAIL") + " " + name)
raise SystemExit(1 if failed else 0)
