"""SDB — cartão OG compartilhável (recibo por token).

Gera PNG 1200x630 (padrão twitter:summary_large_image) com Pillow. O PNG é
servido em /og/<mint>.png e referenciado pelas meta tags de /t/<mint>, para o
preview de link funcionar no X / Discord sem login nem carteira.
"""

import io
import ipaddress
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630

# paleta do tema claro (ver web/style.css)
BG = (250, 245, 236)        # --bg #faf5ec
SURFACE = (255, 255, 255)   # --surface
BORDER = (230, 220, 201)    # --border
TEXT = (45, 42, 36)         # --text #2d2a24
MUTED = (141, 133, 119)     # --muted #8d8577
ACCENT = (226, 86, 42)      # --accent #e2562a
GREEN = (29, 158, 87)       # --green #1d9e57
GREEN_SOFT = (224, 242, 232)

_FONT_CACHE = {}


def _font(size, bold=False, semibold=False):
    key = (size, bold, semibold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = []
    if bold:
        candidates = [
            r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\seguisb.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    elif semibold:
        candidates = [
            r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                f = ImageFont.truetype(p, size)
                _FONT_CACHE[key] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _usd(n):
    if n is None:
        return "—"
    a = abs(n)
    if a >= 1e9:
        return f"${n/1e9:.2f}B"
    if a >= 1e6:
        return f"${n/1e6:.2f}M"
    if a >= 1e3:
        return f"${n/1e3:.1f}K"
    return f"${n:.2f}"


def _tok(n):
    if n is None:
        return "—"
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{n:.2f}"


def _bps(n):
    if n is None:
        return "0%"
    return f"{n/100:.1f}%"


MAX_LOGO_BYTES = 2 * 1024 * 1024


def _public_host(host):
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return all(not ipaddress.ip_address(info[4][0]).is_private
                   and not ipaddress.ip_address(info[4][0]).is_loopback
                   and not ipaddress.ip_address(info[4][0]).is_link_local
                   and not ipaddress.ip_address(info[4][0]).is_reserved
                   for info in infos)
    except (OSError, ValueError):
        return False


MAX_LOGO_REDIRECTS = 2


def _fetch_logo(url):
    if not url:
        return None
    try:
        current = url
        for _ in range(MAX_LOGO_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme != "https" or not parsed.hostname or not _public_host(parsed.hostname):
                return None
            req = urllib.request.Request(current, headers={"User-Agent": "SDB/0.1"})
            with urllib.request.urlopen(req, timeout=4) as r:
                final = (r.geturl() if hasattr(r, "geturl") else None) or current
                final_parsed = urlparse(final)
                if final_parsed.scheme != "https" or not final_parsed.hostname or not _public_host(final_parsed.hostname):
                    return None
                status = getattr(r, "status", None) or getattr(r, "code", None) or 200
                if status in {301, 302, 303, 307, 308}:
                    location = r.headers.get("Location")
                    if not location:
                        return None
                    current = urljoin(final, location)
                    continue
                if not (r.headers.get_content_type() or "").startswith("image/"):
                    return None
                data = r.read(MAX_LOGO_BYTES + 1)
            if len(data) > MAX_LOGO_BYTES:
                return None
            img = Image.open(io.BytesIO(data))
            img.verify()
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            img.thumbnail((192, 192))
            return img
        return None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _circle_logo(img, size):
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _ellipsize(text, font, max_w):
    if not text:
        return ""
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _text_w(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)


def build_png(mint, token, rewards):
    """token: dict de m1.token_metrics. rewards: dict de m3.token_rewards (ou None)."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # faixa superior (cabeçalho)
    d.rectangle([0, 0, W, 84], fill=SURFACE)
    d.line([0, 84, W, 84], fill=BORDER, width=1)
    _text_w(d, (64, 18), "SOLANA STOCK DATABASE", _font(26, semibold=True), TEXT)
    _text_w(d, (64, 52), "memstocks on Solana — yield paid in stocks", _font(18), MUTED)
    mint_disp = "mint " + mint[:6] + "…" + mint[-4:]
    mw = d.textlength(mint_disp, font=_font(20))
    _text_w(d, (W - 64 - int(mw), 34), mint_disp, _font(20), MUTED)

    symbol = token.get("symbol") or "?"
    name = token.get("name") or ""
    terminal = (token.get("terminal") or {}).get("symbol") or ""

    # logo circular
    logo = _fetch_logo(token.get("image_url"))
    y_sym = 132
    if logo:
        circ = _circle_logo(logo, 104)
        img.paste(circ, (64, y_sym), circ)
        sym_x = 196
    else:
        # monograma
        d.ellipse([64, y_sym, 64 + 104, y_sym + 104], fill=ACCENT)
        mono = (symbol[:2]).upper()
        f = _font(40, bold=True)
        tw = d.textlength(mono, font=f)
        _text_w(d, (64 + 52 - tw / 2, y_sym + 26), mono, f, (255, 255, 255))
        sym_x = 196

    # símbolo + nome
    sym_font = _font(64, bold=True)
    sym_w = d.textlength(symbol, font=sym_font)
    _text_w(d, (sym_x, y_sym + 6), symbol, sym_font, TEXT)
    # pill terminal
    if terminal:
        pill_font = _font(22, semibold=True)
        pill_text = "BACKED BY " + terminal
        pw = d.textlength(pill_text, font=pill_font)
        pill_x = sym_x + sym_w + 28
        if pill_x + pw + 36 <= W - 64:
            d.rounded_rectangle([pill_x, y_sym + 16, pill_x + pw + 36, y_sym + 58],
                                radius=21, fill=GREEN_SOFT)
            _text_w(d, (pill_x + 18, y_sym + 26), pill_text, pill_font, GREEN)
    # nome
    name_font = _font(26)
    name = _ellipsize(name, name_font, W - sym_x - 64)
    _text_w(d, (sym_x, y_sym + 74), name, name_font, MUTED)

    # linha de divisão
    d.line([64, 400, W - 64, 400], fill=BORDER, width=1)

    # faixa de estatísticas (3 blocos)
    cells = [
        ("MARKET CAP", _usd((token.get("market") or {}).get("marketCapUsd")), ""),
        ("STACKED TAX", _bps(token.get("stackedTransferTaxBps")),
         f"depth {token.get('depth', '—')}"),
        ("PAID OUT", (_tok((rewards or {}).get("distributedTokens")) + " " + (rewards or {}).get("terminal", "")).strip(),
         "in stock, lifetime"),
    ]
    n = len(cells)
    col_w = (W - 128) / n
    for i, (label, value, sub) in enumerate(cells):
        x = 64 + i * col_w
        _text_w(d, (x, 430), label, _font(22, semibold=True), MUTED)
        val_font = _font(44, bold=True)
        val = _ellipsize(value, val_font, col_w - 4)
        _text_w(d, (x, 466), val, val_font, TEXT)
        if sub:
            _text_w(d, (x, 526), sub, _font(22), MUTED)

    # rodapé
    d.line([64, 578, W - 64, 578], fill=BORDER, width=1)
    _text_w(d, (64, 588), "Statistics only — not investment advice", _font(20), MUTED)
    dom = "Solana Stock Database"
    dw = d.textlength(dom, font=_font(20, semibold=True))
    _text_w(d, (W - 64 - int(dw), 588), dom, _font(20, semibold=True), TEXT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def share_meta(token, rewards):
    """Meta tags (título + descrição) para /t/<mint>."""
    symbol = token.get("symbol") or "?"
    name = token.get("name") or ""
    terminal = (token.get("terminal") or {}).get("symbol") or ""
    mc = _usd((token.get("market") or {}).get("marketCapUsd"))
    tax = _bps(token.get("stackedTransferTaxBps"))
    paid = _tok((rewards or {}).get("distributedTokens"))
    paid_term = (rewards or {}).get("terminal") or ""
    title = f"{symbol} — backed by {terminal}" if terminal else symbol
    desc = f"{name} · market cap {mc} · stacked tax {tax}"
    if paid_term:
        desc += f" · paid out {paid} in {paid_term}"
    return {"title": title, "description": desc}
