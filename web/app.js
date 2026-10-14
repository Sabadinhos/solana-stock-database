const HOME_TOKEN_LIMIT = 9;
const state = {
  range: "ALL", sort: "mc", stats: ["mc", "paid", "tax"],
  theme: localStorage.getItem("sdb-theme") || "dark", offset: 0, total: Infinity,
  loading: false, detail: false, homeOnly: false,
};

const draft = { stats: [...state.stats], sort: state.sort };
const THEME_ORDER = ["auto", "light", "dark"];

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const grid = $("#grid");
const sentinel = $("#sentinel");
const loadState = $("#load-state");
const hint = $("#search-across");
const drawer = $("#drawer");
const backdrop = $("#backdrop");
const menuBtn = $("#menu-btn");
const statNote = $("#stat-note");
const applyNote = $("#apply-note");
const ticker = $("#ticker");
const tickerTrack = $("#ticker-track");
const homeFeatured = $("#home-featured");
const homeBento = $("#home-bento");

const fmt = {
  usd(n) {
    if (n == null) return "-";
    if (Math.abs(n) >= 1e9) return "$" + (n / 1e9).toFixed(2) + "B";
    if (Math.abs(n) >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
    if (Math.abs(n) >= 1e3) return "$" + (n / 1e3).toFixed(1) + "K";
    return "$" + n.toFixed(2);
  },
  tok(n) {
    if (n == null) return "-";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toFixed(2);
  },
  int(n) { return n == null ? "-" : n.toLocaleString("en-US"); },
  bps(n) { return n == null ? "0%" : (n / 100).toFixed(1) + "%"; },
  pct(n) {
    if (n == null) return "-";
    return (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
  },
  date(s) { return s ? s.slice(0, 10) : "-"; },
  stock(n) {
    if (n == null) return "-";
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  price(n) {
    if (n == null) return "-";
    if (n === 0) return "$0";
    if (n < 0.000001) return "$" + n.toFixed(10);
    if (n < 0.001) return "$" + n.toFixed(8);
    return "$" + n.toFixed(6);
  },
};

async function api(path) {
  const r = await fetch("/api" + path, { headers: { Accept: "application/json" } });
  const text = await r.text();
  let body = {}; try { body = text ? JSON.parse(text) : {}; } catch (e) { throw new Error("Invalid API response"); }
  if (!r.ok) throw new Error(body.message || body.error || `HTTP ${r.status}`);
  return body;
}

function triangle(v) {
  if (v == null) return "";
  return `<span class="tri ${v >= 0 ? "up" : "down"}">${v >= 0 ? "▲" : "▼"}</span>`;
}

function shortAddr(m) {
  return m ? m.slice(0, 6) + "…" + m.slice(-4) : "";
}
function curatedWallet(addr) {
  const key = String(addr || "").trim();
  return key && window.SDB_CURATED_WALLETS ? window.SDB_CURATED_WALLETS[key] || null : null;
}
function hashSeed(value) {
  let h = 2166136261;
  for (const ch of String(value || "?")) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}
function identiconData(value) {
  const h = hashSeed(value), bg = `hsl(${h % 360} 48% 32%)`, fg = `hsl(${(h >>> 8) % 360} 78% 68%)`;
  let cells = "";
  for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) if (((h >>> ((y * 3 + x) % 24)) ^ h) & 1) { cells += `<rect x="${x * 6 + 1}" y="${y * 6 + 1}" width="5" height="5"/><rect x="${(4 - x) * 6 + 1}" y="${y * 6 + 1}" width="5" height="5"/>`; }
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="16" fill="${bg}"/><g fill="${fg}">${cells}</g></svg>`)}`;
}
function walletIdentityHtml(addr, compact = false) {
  const record = curatedWallet(addr);
  const label = record && record.displayName ? record.displayName : shortAddr(addr);
  const avatar = record && imgUrl(record.avatarUrl);
  const fallback = identiconData(addr);
  const avatarHtml = avatar
    ? `<img class="wallet-avatar" src="${esc(avatar)}" alt="" loading="lazy" decoding="async" data-fallback="${esc(fallback)}" onerror="this.src=this.dataset.fallback;this.onerror=null">`
    : `<img class="wallet-avatar" src="${fallback}" alt="" aria-hidden="true">`;
  const badge = record ? `<span class="wallet-badge">${esc(record.label || record.kind || "Curated wallet")}</span>` : "";
  const source = record && record.sourceUrl ? ` title="Curated identity · source: ${esc(record.sourceUrl)}"` : ` title="Wallet address"`;
  return `<span class="wallet-identity${compact ? " compact" : ""}"${source} data-wallet="${esc(addr)}">${avatarHtml}<span class="wallet-copy"><strong>${esc(label)}</strong><small>${shortAddr(addr)}</small></span>${badge}</span>`;
}
function contractChip(m) {
  return m ? `<button class="contract" data-copy="${m}" title="Copy contract address" type="button">${shortAddr(m)} <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>` : "";
}
function imgUrl(u) {
  if (!u) return "";
  try {
    const raw = /^https?:\/\//i.test(String(u)) ? String(u) : "https://www.stonkfun.xyz" + String(u);
    const parsed = new URL(raw);
    return parsed.protocol === "https:" ? parsed.href : "";
  } catch (e) { return ""; }
}
const ASSET_COLORS = {
  NVDA:{l:["#eaf6d6","#3d6b00"],d:["#26330f","#a5e05a"]}, SPY:{l:["#e2ecff","#1a4bb8"],d:["#1a2540","#7fa8ff"]},
  OPENAI:{l:["#dcf2ea","#0a7a5c"],d:["#0f2b23","#3fd6a8"]}, GME:{l:["#ffe1e6","#b3002d"],d:["#331420","#ff6b8a"]},
  HOOD:{l:["#e6f6ec","#0a7d3a"],d:["#122a1b","#5fd688"]}, BRK:{l:["#e3eef3","#1b4965"],d:["#132630","#6fb3d6"]},
  ANTHROPIC:{l:["#f4e9df","#8a5a2b"],d:["#2b2015","#d4a27f"]}
};
function assetColor(sym) { const key=String(sym||"").toUpperCase().replace(/X$/,""), m=ASSET_COLORS[key]; const dark=document.documentElement.dataset.theme==="dark"; if(m)return m[dark?"d":"l"]; const h=[...key].reduce((a,c)=>a+c.charCodeAt(0),0)%360; return dark?[`hsl(${h} 40% 16%)`,`hsl(${h} 70% 70%)`]:[`hsl(${h} 60% 92%)`,`hsl(${h} 55% 32%)`];}
const ASSET_LOGOS = {
  NVDA: "nvidia", NVIDIA: "nvidia", SOL: "solana", ZEC: "zcash", ANTHROPIC: "anthropic",
  AAPL: "apple/ffffff", APPLE: "apple", MSFT: "microsoft", MICROSOFT: "microsoft", TSLA: "tesla",
  TESLA: "tesla", HOOD: "robinhood", ROBINHOOD: "robinhood", META: "meta", AMAZON: "amazon",
  AMZN: "amazon", GOOGL: "google", GOOGLE: "google", COIN: "coinbase", COINBASE: "coinbase",
  GME: "gamestop", GAMESTOP: "gamestop", MCD: "mcdonalds", MCDONALDS: "mcdonalds",
  QQQ: "nasdaq", PLTR: "palantir", JUP: "jupiter", WBTC: "wrappedbitcoin"
};
function baseTicker(sym) {
  return String(sym || "").toUpperCase().replace(/X$/, "").replace(/^SPCX$/, "SPX");
}
function assetLogoUrl(sym) {
  const key = baseTicker(sym);
  const slug = ASSET_LOGOS[key];
  return slug ? `https://cdn.simpleicons.org/${slug}` : "";
}
function assetChip(sym) {
  const [bg,ink]=assetColor(sym);
  const logo = assetLogoUrl(sym);
  const icon = logo ? `<span class="asset-logo-wrap"><img class="asset-logo" src="${logo}" alt="" loading="lazy" decoding="async" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="asset-logo-fallback" aria-hidden="true">${esc(String(sym||"?").slice(0,2).toUpperCase())}</span></span>` : `<span class="asset-logo-fallback" aria-hidden="true">${esc(String(sym||"?").slice(0,2).toUpperCase())}</span>`;
  const ticker = baseTicker(sym);
  const badge = `<span class="asset-cap-badge"><span><small>Stock</small><b class="cap-stock" data-ticker="${esc(ticker)}">-</b></span><span><small>Crypto</small><b class="cap-crypto" data-quote="${esc(sym || "")}">-</b></span></span>`;
  return `<span class="asset-chip" style="--asset-color:${bg};--asset-ink:${ink}">${icon}<span>${esc(sym||"-")}</span>${badge}</span>`;
}
function tokenIcon(mint, symbol, image, cls="token-icon") {
  const fallback = `https://www.stonkfun.xyz/api/asset/quote-logo/${encodeURIComponent(mint || "")}`;
    const metadata = `/api/asset/${encodeURIComponent(mint || "")}/image`;
    const first = imgUrl(image) || metadata;
  const letter = esc(String(symbol || "?").slice(0, 2).toUpperCase());
  const classes = `${cls} token-icon-safe`;
  return `<span class="${classes}" aria-hidden="true"><span class="token-icon-ph">${letter}</span><img src="${esc(first)}" alt="" loading="lazy" decoding="async" data-fallback="${esc(fallback)}" onerror="if(this.dataset.fallback&&this.src!==this.dataset.fallback){this.src=this.dataset.fallback;this.dataset.fallback=''}else{this.style.display='none';this.previousElementSibling.style.display='inline-flex'}"></span>`;
}
function esc(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
function copyText(txt, btn) {
  const done = () => {
    btn.textContent = "Copied ✓";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = shortAddr(txt); btn.classList.remove("copied"); }, 1400);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(done).catch(() => {});
  } else {
    const ta = document.createElement("textarea");
    ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    ta.remove();
  }
}

function statValue(key, c) {
  switch (key) {
    case "mc": return { label: "MC", value: fmt.usd(c.market_cap_usd), tri: c.price_change_24h };
    case "paid": return { label: "Paid out (in " + (c.terminal || "-") + ")", value: fmt.tok(c.distributed_tokens) };
    case "tax": return { label: "Stacked tax", value: fmt.bps(c.stacked_tax_bps) };
    case "volume": return { label: "Volume 24h", value: fmt.usd(c.volume_24h_usd) };
    case "fdv": return { label: "FDV", value: fmt.usd(c.fdv_usd) };
    case "price": return { label: "Price", value: fmt.price(c.price_usd) };
    case "holders": return { label: "Holders", value: fmt.int(c.holder_count) };
    case "payouts": return { label: "Payouts", value: fmt.int(c.payout_count) };
    case "change": return { label: "Change 24h", value: fmt.pct(c.price_change_24h), tri: c.price_change_24h };
    case "peak": return { label: "Peak MC", value: fmt.usd(c.peak_market_cap_usd) };
    default: return { label: "", value: "-" };
  }
}

function cardHtml(c) {
  const stats = state.stats.map(k => {
    const s = statValue(k, c);
    return `<div class="stat"><div class="s-label">${s.label}</div><div class="s-value">${s.value}${triangle(s.tri)}</div></div>`;
  }).join("");
  return `<article class="card" role="listitem" tabindex="0" data-mint="${esc(c.mint)}" aria-label="${esc(c.symbol || c.mint)}">
    <div class="card-icon">${tokenIcon(c.mint, c.symbol, c.image_url, "token-icon card-token-icon")}</div>
    <div class="card-symbol">${esc(c.symbol) || "-"}</div>
    <div class="card-name">${esc(c.name) || ""}</div>
    ${contractChip(c.mint)}
    <div class="card-stats">${stats}</div>
    <div class="card-foot">Depth ${c.depth ?? "-"} · Last payout: ${fmt.date(c.last_payout_at)}</div>
  </article>`;
}

function showLoad(msg) {
  loadState.textContent = msg || "Loading…";
  loadState.classList.add("show");
}
function hideLoad() { loadState.classList.remove("show"); }

let io = null;
let compareA = null;
let compareB = null;
const cmpDate = { a: null, b: null };
let contentPainted = false;

function initObserver() {
  if (io) io.disconnect();
  io = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadMore();
  }, { rootMargin: "700px" });
  io.observe(sentinel);
}

async function loadMore() {
  if (state.loading || state.detail || state.offset >= state.total) return;
  state.loading = true;
  showLoad();
  let d;
  try {
    d = await api(`/cards?range=${state.range}&sort=${state.sort}&limit=${state.homeOnly ? HOME_TOKEN_LIMIT : 30}&offset=${state.offset}`);
  } catch (e) {
    state.loading = false;
    loadState.textContent = "Could not load tokens. Try again.";
    return;
  }
  state.total = d.total;
  const cards = d.cards;
  if (state.offset === 0 && cards.length === 0) {
    grid.innerHTML = `<p class="empty" style="grid-column:1/-1;text-align:center;color:var(--muted);padding:40px 0">No payouts in this range yet.</p>`;
  } else {
    grid.insertAdjacentHTML("beforeend", cards.map(cardHtml).join(""));
  }
  state.offset += cards.length;
  state.loading = false;
  hideLoad();
  if (!contentPainted) {
    contentPainted = true;
    applyTheme(true);
  }
  if (state.homeOnly || state.offset >= state.total) { if (io) io.disconnect(); }
}

function resetAndLoad() {
  state.offset = 0; state.total = Infinity; grid.innerHTML = "";
  if (state.homeOnly) { if (io) io.disconnect(); } else initObserver();
  loadMore();
}

function openDrawer() {
  draft.stats = [...state.stats];
  draft.sort = state.sort;
  syncDraftUI();
  statNote.textContent = "";
  applyNote.textContent = "";
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.classList.add("open");
  menuBtn.setAttribute("aria-expanded", "true");
  $("#drawer-close").focus();
}
function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.remove("open");
  menuBtn.setAttribute("aria-expanded", "false");
  menuBtn.focus();
}

function syncDraftUI() {
  $$("[data-stat]").forEach(b => {
    const on = draft.stats.includes(b.dataset.stat);
    b.classList.toggle("selected", on);
    b.setAttribute("aria-checked", String(on));
  });
  $$("[data-sort]").forEach(b => {
    const on = b.dataset.sort === draft.sort;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", String(on));
  });
}

function shake(el) {
  el.classList.add("shake");
  setTimeout(() => el.classList.remove("shake"), 300);
}

function hasPending() {
  return draft.sort !== state.sort || draft.stats.join(",") !== state.stats.join(",");
}

function toggleStat(key) {
  const chip = $(`[data-stat="${key}"]`);
  const sel = chip.classList.contains("selected");
  if (sel) {
    if (draft.stats.length <= 1) {
      statNote.textContent = "At least 1 stat is required.";
      shake(chip);
      return;
    }
    draft.stats = draft.stats.filter(s => s !== key);
  } else {
    if (draft.stats.length >= 3) {
      statNote.textContent = "Up to 3 stats.";
      shake(chip);
      return;
    }
    draft.stats.push(key);
  }
  syncDraftUI();
  statNote.textContent = "";
  applyNote.textContent = "Press Apply to update the cards.";
}

function setDraftSort(sort) {
  draft.sort = sort;
  syncDraftUI();
  applyNote.textContent = "Press Apply to update the cards.";
}

function applyDraft() {
  state.stats = [...draft.stats];
  state.sort = draft.sort;
  resetAndLoad();
  applyNote.textContent = "Applied.";
  statNote.textContent = "";
  setTimeout(() => { if (applyNote.textContent === "Applied.") applyNote.textContent = ""; }, 1500);
}

function setRange(range) {
  state.range = range;
  $$("[data-range]").forEach(b => {
    const on = b.dataset.range === range;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", String(on));
  });
  resetAndLoad(); loadHomeFeatured();
}

function applyTheme() {
  const requested = state.theme === "auto"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : state.theme;
  const t = !contentPainted && requested === "light" ? "dark" : requested;
  document.documentElement.setAttribute("data-theme", t);
  $$("#theme-btn .ico").forEach(ico => ico.classList.toggle("active", ico.dataset.ico === state.theme));
}

function setTheme(t) {
  state.theme = t;
  localStorage.setItem("sdb-theme", t);
  applyTheme();
}

function cycleTheme() {
  const i = THEME_ORDER.indexOf(state.theme);
  setTheme(THEME_ORDER[(i + 1) % THEME_ORDER.length]);
}

function bindCard(card) {
  card.addEventListener("click", () => location.hash = "#/token/" + card.dataset.mint);
  card.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      location.hash = "#/token/" + card.dataset.mint;
    }
  });
}

function pill(cls, txt) {
  return txt ? `<span class="pill ${cls}">${txt}</span>` : "";
}

function xHandle(url) {
  if (!url) return null;
  const m = url.match(/x\.com\/([^/?#]+)/i) || url.match(/twitter\.com\/([^/?#]+)/i);
  return m ? "@" + m[1] : url;
}

function socialLinks(t) {
  const parts = [];
  if (t.twitter) parts.push(`<a class="shortcut" href="${esc(t.twitter)}" target="_blank" rel="noopener noreferrer">${esc(xHandle(t.twitter))} ↗</a>`);
  if (t.website) parts.push(`<a class="shortcut" href="${esc(t.website)}" target="_blank" rel="noopener noreferrer">Website ↗</a>`);
  return parts.length ? `<div class="shortcuts">${parts.join("")}</div>` : "";
}

function shortcutRow(mint) {
  return `<div class="shortcuts">
    <a class="shortcut" href="https://solscan.io/token/${mint}" target="_blank" rel="noopener noreferrer">Solscan ↗</a>
    <a class="shortcut" href="https://bubblemaps.io/sol/token/${mint}" target="_blank" rel="noopener noreferrer">Bubblemaps ↗</a>
    <a class="shortcut" href="https://www.stonkfun.xyz/" target="_blank" rel="noopener noreferrer">StonkFun ↗</a>
    <button class="shortcut share-btn" data-mint="${mint}" type="button">Share card</button>
  </div>`;
}

function advancedHtml(on) {
  const ev = (on.events || []).map(e => `${e.kind} ×${e.c}`).join(" · ");
  const holders = (on.holders || []).slice(0, 6).map(h =>
    `${shortAddr(h.owner)} ${(h.pct * 100).toFixed(1)}%`).join("<br>");
  return `
    <section class="d-section">
      <h3>Advanced (onchain)</h3>
      <div class="m-grid">
        ${metric("Holder top-10 share", on.holderTop10Share != null ? (on.holderTop10Share * 100).toFixed(1) + "%" : "-")}
        ${metric("Onchain events", ev || "none")}
        ${metric("Pool program", on.pool ? shortAddr(on.pool.program) : "-")}
        ${metric("Burn events", on.burn ? fmt.int(on.burn.burnEvents) : "-")}
      </div>
      ${holders ? `<div class="audit-sub"><h4>Top holders</h4><p class="mono">${holders}</p></div>` : ""}
    </section>`;
}

function shareToken(mint, btn) {
  const url = location.origin + "/t/" + mint;
  const done = () => {
    btn.textContent = "Copied ✓";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "Share card"; btn.classList.remove("copied"); }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(done).catch(() => {});
  } else {
    const ta = document.createElement("textarea");
    ta.value = url;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    ta.remove();
  }
}

function metric(label, value, sub) {
  return `<div class="m"><div class="m-l">${label}</div><div class="m-v">${value}</div>${sub ? `<div class="m-s">${sub}</div>` : ""}</div>`;
}
function wikiChart(t) {
  const market = Number(t.market.marketCapUsd) || 0;
  const peak = Number(t.market.peakMarketCapUsd) || market;
  const bottleneck = Number(t.thinnestLinkMarketCapUsd) || market;
  const max = Math.max(market, peak, bottleneck, 1);
  const bars = [
    ["Current market cap", market, "var(--accent)"],
    ["Chain bottleneck", bottleneck, "var(--green)"],
    ["All-time peak", peak, "var(--orange)"]
  ];
  const svgBars = bars.map((b, i) => {
    const y = 28 + i * 42;
    const width = Math.max(8, b[1] / max * 430);
    return `<text x="0" y="${y}" class="wiki-chart-label">${esc(b[0])}</text><rect x="150" y="${y - 13}" width="430" height="18" rx="9" class="wiki-chart-track"/><rect x="150" y="${y - 13}" width="${width.toFixed(1)}" height="18" rx="9" fill="${b[2]}"/><text x="590" y="${y}" class="wiki-chart-value">${esc(fmt.usd(b[1]))}</text>`;
  }).join("");
  return `<div class="wiki-chart-wrap"><svg class="wiki-chart" viewBox="0 0 760 155" role="img" aria-label="Token market profile comparison">${svgBars}</svg><p class="wiki-chart-note">Market profile from indexed current, chain bottleneck and peak values. This is not a time-series forecast.</p></div>`;
}

function statusPill(s) {
  const cls = s === "graduated" ? "xstock" : s === "dead" ? "dead" : "new";
  return `<span class="pill ${cls}">${s}</span>`;
}

function minutesBetween(a, b) {
  if (!a || !b) return null;
  return Math.round((new Date(b) - new Date(a)) / 60000);
}

function auditHtml(audit, portfolio) {
  const subs = [];
  if (audit && audit.launch) {
    const l = audit.launch, cu = audit.current;
    let chg = "";
    if (audit.changes && audit.changes.length) {
      chg = `<div class="chg-list">` + audit.changes.map(c => {
        const from = c.field === "transferFee" ? fmt.bps(c.fromBps) : c.from;
        const to = c.field === "transferFee" ? fmt.bps(c.toBps) : c.to;
        return `<span class="chg">${c.label}: <s>${from}</s> → ${to}</span>`;
      }).join("") + `</div>`;
    } else {
      chg = `<p class="muted note">No config changes since launch (fee, quote, mode).</p>`;
    }
    const mins = minutesBetween(l.createdAt, cu.graduatedAt);
    const gradSub = cu.graduatedAt ? `graduated in ${mins != null ? mins : "-"} min` : "";
    subs.push(`
      <div class="audit-sub">
        <h4>This token</h4>
        <div class="m-grid">
          ${metric("Launched", fmt.date(l.createdAt), l.launchpad || "")}
          ${metric("Initial fee", fmt.bps(l.transferFeeBps))}
          ${metric("Start MC", fmt.usd(l.startMarketCapUsd))}
          ${metric("Status", statusPill(cu.status), gradSub)}
        </div>
        ${chg}
      </div>`);
  }
  if (portfolio && portfolio.length) {
    const rows = portfolio.map(t => `
      <div class="asset-row" data-mint="${t.mint}" tabindex="0" role="button" aria-label="${esc(t.symbol)}">
        <span class="a-sym">${tokenIcon(t.mint,t.symbol,t.image_url,"token-icon list-token-icon")}${esc(t.symbol)}</span>
        <span class="a-name muted">${esc(t.name) || ""}</span>
        ${statusPill(t.status)}
        <span class="a-num">${fmt.usd(t.marketCapUsd)}</span>
      </div>`).join("");
    subs.push(`
      <div class="audit-sub">
        <h4>Other tokens from this wallet <span class="count-note">(${portfolio.length})</span></h4>
        <div class="asset-list">${rows}</div>
      </div>`);
  }
  if (!subs.length) return "";
  return `<section class="d-section" data-sec="creator"><h3>Dev wallet</h3>${subs.join("")}</section>`;
}

function filterButton(f, label, active) {
  return `<button class="filter-btn${active ? " active" : ""}" data-filter="${f}" role="tab" aria-selected="${active}" type="button">${label}</button>`;
}

function applyTokenFilter(f) {
  $$(".filter-btn").forEach(b => {
    const on = b.dataset.filter === f;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  let visible = 0;
  $$(".d-section[data-sec]").forEach(sec => {
    const show = f === "all" || sec.dataset.sec === f;
    sec.classList.toggle("hidden", !show);
    if (show) visible++;
  });
  const empty = $("#token-filter-empty");
  if (empty) empty.classList.toggle("hidden", visible > 0);
}

async function renderToken(mint) {
  beginDetail();
  ticker.classList.add("hidden");
  if (io) io.disconnect();
  sentinel.classList.add("hidden");
  $(".fade-bottom").classList.add("hidden");
  grid.className = "detail";
  grid.removeAttribute("role");
  grid.removeAttribute("aria-label");
  grid.innerHTML = `<p class="empty" style="text-align:center;color:var(--muted);padding:60px 0">Loading…</p>`;
  const d = await api(`/token/${mint}`);
  if (!d.found) {
    grid.innerHTML = `<div class="detail-inner"><button class="back" onclick="location.hash=''">← Back</button><p class="empty" style="color:var(--muted)">Token not found.</p></div>`;
    return;
  }
  const t = d.token, r = d.rewards, c = d.creator, au = d.audit, pf = d.portfolio;
  const on = d.onchain || {};
  const decomposition = d.decomposition;
  const decompositionHtml = decomposition ? `<section class="d-section" data-sec="market"><h3>Return decomposition</h3><div class="m-grid">${metric("Token in USD", fmt.pct(decomposition.tokenReturnUsd))}${metric("${esc(decomposition.terminal)} terminal", fmt.pct(decomposition.terminalReturn))}${metric("Relative to terminal", fmt.pct(decomposition.relativeReturn), decomposition.points + " aligned points")}</div><p class="muted">${decomposition.terminalStale ? "Terminal market closed / last observation is stale." : "Terminal price series is current within the indexed window."}</p></section>` : `<section class="d-section" data-sec="market"><h3>Return decomposition</h3><p class="muted">No price history yet.</p></section>`;
  const img = tokenIcon(t.mint,t.symbol,t.image_url,"token-icon hero-token-icon");
  const change = t.market.priceChange24h;
  const chgCls = change == null ? "" : (change >= 0 ? "pos" : "neg");
  const chgTxt = change == null ? "-" : ((change >= 0 ? "▲ " : "▼ ") + Math.abs(change).toFixed(1) + "%");
  const turnover = (t.market.volume24hUsd && t.market.marketCapUsd)
    ? (t.market.volume24hUsd / t.market.marketCapUsd * 100) : null;
  const gradPct = t.graduationProgress != null ? (t.graduationProgress * 100).toFixed(1) + "%" : "-";
  const simulator = r && t.quoteOnlyFees ? `<section class="d-section yield-simulator" data-sec="yield"><h3>Fee distribution simulator</h3><p class="muted">Estimated ${esc(t.terminal.symbol)} from current fees.</p><div class="simulator-fields"><label>Amount held (USD)<input id="token-sim-amount" class="num" inputmode="decimal" value="10" min="0" step="0.01"></label></div><div class="m-grid"><div class="metric"><span class="m-k">24h estimate</span><strong class="m-v" id="token-sim-24-usd">-</strong><small id="token-sim-24-tokens">-</small></div><div class="metric"><span class="m-k">30-day estimate</span><strong class="m-v" id="token-sim-30-usd">-</strong><small id="token-sim-30-tokens">-</small></div><div class="metric"><span class="m-k">1-year estimate</span><strong class="m-v" id="token-sim-365-usd">-</strong><small id="token-sim-365-tokens">-</small></div></div><p class="calc-foot">Volume 24h × stacked fee × (holding ÷ market cap). Estimate.</p></section>` : "";

  const chainHtml = `<div class="chain">
    <div class="node"><div class="n-s">${esc(t.symbol)}</div></div>
    ${(t.chain || []).map(h => `<span class="arrow">→</span><div class="node"><div class="n-s">${esc(h.symbol)}</div></div>`).join("")}
    <span class="arrow">→</span><div class="node term"><div class="n-s">${esc(t.terminal.symbol)}</div><div class="n-sub">${esc(t.terminal.categoryLabel || t.terminal.category)}</div></div>
  </div>`;

  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <div class="d-head">
      ${img}
      <div class="d-title">
        <div class="d-sym-row"><h2>${esc(t.symbol)}</h2>${pill("xstock", esc(t.terminal.symbol))}${pill("mode", esc(t.mode))}</div>
        <p class="muted">${esc(t.name) || ""}</p>
        <div class="head-price">
          <span class="hp-price">${fmt.price(t.market.priceUsd)}</span>
          <span class="hp-change ${chgCls}">${chgTxt}</span>
          <span class="hp-pair">paired with ${esc(t.terminal.symbol)}</span>
        </div>
      </div>
    </div>
    <p class="mono">${t.mint}</p>
    <div class="head-actions">${socialLinks(t)}${shortcutRow(t.mint)}</div>
    <section class="wiki-intro"><div><span class="section-kicker">Token encyclopedia</span><h3>About ${esc(t.symbol)}</h3><p>${esc(t.name || t.symbol)} is an indexed Solana token paired with ${esc(t.terminal.symbol)}. SDB records its market state, payout history, creator activity and backing chain from public API and onchain evidence. This page is a factual snapshot, not an endorsement.</p></div><aside class="wiki-infobox"><div class="wiki-infobox-title">${img}${esc(t.symbol)}</div><div><b>Network</b><span>Solana</span></div><div><b>Launchpad</b><span>${esc(t.launchpad || "Unknown")}</span></div><div><b>Status</b><span>${statusPill(t.status)}</span></div><div><b>Quote asset</b><span>${assetChip(t.terminal.symbol)}</span></div><div><b>Created</b><span>${fmt.date(t.createdAt)}</span></div></aside></section>
    ${wikiChart(t)}

    <div class="filter-row" role="tablist" aria-label="Token views">
      ${filterButton("all", "ALL", true)}
      ${filterButton("market", "Market")}
      ${filterButton("backing", "Backing")}
      ${filterButton("yield", "Yield")}
      ${filterButton("creator", "Creator")}
    </div>

    <section class="d-section" data-sec="market"><h3>Market</h3><div class="m-grid">
      ${metric("Market cap", fmt.usd(t.market.marketCapUsd))}
      ${metric("Volume 24h", fmt.usd(t.market.volume24hUsd))}
      ${metric("FDV", fmt.usd(t.market.fdvUsd))}
      ${metric("24h change", chgTxt, "vs USD")}
      ${metric("All-time peak", fmt.usd(t.market.peakMarketCapUsd))}
      ${metric("Turnover 24h", turnover != null ? turnover.toFixed(1) + "%" : "-", "volume ÷ market cap")}
      ${metric("Graduation", gradPct, "progress")}
      ${metric("Price", fmt.price(t.market.priceUsd))}
    </div></section>
    ${decompositionHtml}

    <section class="d-section" data-sec="backing"><h3>Backing</h3>
      ${chainHtml}
      <div class="m-grid" style="margin-top:12px">
        ${metric("Depth", t.depth + (t.depth === 1 ? " hop" : " hops"))}
        ${metric("Stacked tax", fmt.bps(t.stackedTransferTaxBps))}
        ${metric("Terminal asset", esc(t.terminal.symbol), esc(t.terminal.name || t.terminal.categoryLabel))}
        ${metric("Bottleneck MC", fmt.usd(t.thinnestLinkMarketCapUsd))}
        ${on.burn && on.burn.totalBurnedUi ? metric("Burned (buyback/burn)", fmt.tok(on.burn.totalBurnedUi), on.burn.burnValueUsd != null ? fmt.usd(on.burn.burnValueUsd) + " burned" : "") : ""}
      </div>
    </section>

    ${r ? `<section class="d-section" data-sec="yield"><h3>Yield in stock</h3><div class="m-grid">
      ${metric("Paid out (in " + esc(r.terminal) + ")", fmt.tok(r.distributedTokens))}
      ${metric("Payouts", fmt.int(r.payoutCount))}
      ${metric("Holders", fmt.int(r.holderCount))}
      ${metric("Last payout", fmt.date(r.lastPayoutAt))}
    </div></section>${simulator}` : ""}

    ${c ? `<section class="d-section" data-sec="creator"><h3>Creator</h3><div class="m-grid">
      ${metric("Launches", fmt.int(c.launches))}
      ${metric("Graduated", fmt.int(c.graduated))}
      ${metric("Dead", fmt.int(c.dead))}
      ${metric("Median peak", fmt.usd(c.medianPeakMarketCapUsd), c.medianTimeToGraduationMin != null ? "peak in " + Math.round(c.medianTimeToGraduationMin) + " min" : "")}
    </div>${c.x && c.x.dominant ? `<p class="x-note"><span class="unverified ${c.x.status}">${c.x.status === "verified" ? "Verified creator" : c.x.status === "likely" ? "Likely creator" : "Linked X · unverified"}</span> <a href="${c.x.dominant}" target="_blank" rel="noopener">${xHandle(c.x.dominant)}</a> · appears on ${c.x.linkedCount} token${c.x.linkedCount === 1 ? "" : "s"} from this wallet.</p>` : ""}</section>` : ""}

    ${auditHtml(au, pf)}
    ${advancedHtml(on)}
    <p class="muted hidden" id="token-filter-empty" style="text-align:center;padding:24px 0">Nothing to show in this view.</p>
  </div>`;
  const shareBtn = grid.querySelector(".share-btn");
  if (shareBtn) shareBtn.addEventListener("click", () => shareToken(shareBtn.dataset.mint, shareBtn));
  grid.querySelectorAll(".asset-row").forEach(row => {
    const go = () => location.hash = "#/token/" + row.dataset.mint;
    row.addEventListener("click", go);
    row.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  });
  grid.querySelectorAll(".filter-btn").forEach(b => {
    b.addEventListener("click", () => applyTokenFilter(b.dataset.filter));
  });
  const simAmount = $("#token-sim-amount");
  if (simAmount) {
    const updateSimulator = () => {
      const held = Math.max(0, Number.parseFloat(simAmount.value) || 0);
      const volume = Number(t.market.volume24hUsd) || 0;
      const marketCap = Number(t.market.marketCapUsd) || 0;
      const fee = Number(t.stackedTransferTaxBps) || 0;
      const terminalPrice = Number(t.terminalPriceUsd) || 0;
      const base = volume > 0 && marketCap > 0 && fee > 0 ? volume * (fee / 10000) * (held / marketCap) : null;
      [1, 30, 365].forEach(days => {
        const usd = base == null ? null : base * days;
        const units = usd == null || terminalPrice <= 0 ? null : usd / terminalPrice;
        const usdEl = $(`#token-sim-${days}-usd`), unitsEl = $(`#token-sim-${days}-tokens`);
        if (usdEl) usdEl.textContent = usd == null ? "Unavailable" : fmt.usd(usd);
        if (unitsEl) unitsEl.textContent = units == null ? "terminal units unavailable" : `${fmt.tok(units)} ${t.terminal.symbol} units`;
      });
    };
    simAmount.addEventListener("input", updateSimulator);
    updateSimulator();
  }
}

function beginDetail() {
  state.homeOnly = false;
  state.detail = true;
  if (homeFeatured) homeFeatured.classList.add("hidden");
  if (homeBento) homeBento.classList.add("hidden");
  ticker.classList.add("hidden");
  menuBtn.classList.add("hidden");
  if (io) io.disconnect();
  sentinel.classList.add("hidden");
  $(".fade-bottom").classList.add("hidden");
  grid.className = "detail";
  grid.removeAttribute("role");
  grid.removeAttribute("aria-label");
}

function backBtn() {
  return `<button class="back" onclick="location.hash=''">← Back</button>`;
}

async function renderAsset(symbol) {
  beginDetail();
  grid.innerHTML = `<p class="empty" style="text-align:center;color:var(--muted);padding:60px 0">Loading…</p>`;
  const d = await api(`/assets/${encodeURIComponent(symbol)}`);
  if (!d.found) {
    grid.innerHTML = `<div class="detail-inner">${backBtn()}<p class="empty" style="color:var(--muted)">Asset not found.</p></div>`;
    return;
  }
  const a = d.asset;
  const tokens = a.tokens.map(t => `
    <div class="asset-row" data-mint="${t.mint}" tabindex="0" role="button" aria-label="${esc(t.symbol)}">
      <span class="a-sym">${tokenIcon(t.mint,t.symbol,t.image_url,"token-icon list-token-icon")}${esc(t.symbol)}</span>
      <span class="a-name muted">${esc(t.name) || ""}</span>
      <span class="a-num">${fmt.usd(t.market_cap_usd)}</span>
      <span class="a-num muted">${t.depth} hop${t.depth === 1 ? "" : "s"}</span>
    </div>`).join("");
  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <div class="d-head"><div><h2>${esc(a.symbol)}</h2><p class="muted">${esc(a.categoryLabel || a.category)} · ${fmt.int(a.tokenCount)} tokens backed by it</p></div></div>
    <div class="m-grid">
      ${metric("Tokens backed", fmt.int(a.tokenCount))}
      ${metric("Total market cap", fmt.usd(a.totalMarketCapUsd))}
      ${metric("Yield paid out", fmt.tok(a.yieldTotal) + " " + a.symbol)}
      ${metric("Reward coins", fmt.int(a.rewardCoins))}
    </div>
    <section class="d-section"><h3>Tokens backed by ${a.symbol}</h3><div class="asset-list">${tokens || `<p class="muted">None.</p>`}</div></section>
  </div>`;
  grid.querySelectorAll(".asset-row").forEach(r => {
    const go = () => location.hash = "#/token/" + r.dataset.mint;
    r.addEventListener("click", go);
    r.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  });
}

function renderLaunchLineChart(items){
  const rows=items&&items.assets?items.assets:[]; const max=Math.max(1,...rows.map(x=>Number(x.launches)||0));
  const w=760,h=230,pad=28; const pts=rows.slice(0,14).map((x,i)=>{const xx=pad+(i*Math.max(1,(w-pad*2)/Math.max(1,rows.slice(0,14).length-1)));const yy=h-pad-(Number(x.launches)||0)/max*(h-pad*2);return [xx,yy,x];});
  const path=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  return `<svg class="launch-line-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Launches by underlying asset"><path class="chart-axis" d="M${pad} ${h-pad}H${w-pad}"/><path class="chart-line" d="${path}"/>${pts.map(p=>`<circle class="chart-dot" cx="${p[0]}" cy="${p[1]}" r="4"><title>${esc(p[2].terminal)}: ${fmt.int(p[2].launches)} launches</title></circle>`).join('')}</svg>`;
}

async function renderInsights() {
  beginDetail();
  grid.innerHTML = `<p class="empty" style="text-align:center;color:var(--muted);padding:60px 0">Loading…</p>`;
  const [att, surv] = await Promise.all([api("/attention?days=7"), api("/survival")]);
  const attRows = att.assets.slice(0, 7).map((x, i) => `
    <div class="i-row" data-asset="${esc(x.terminal)}" tabindex="0" role="button" aria-label="${esc(x.terminal)}">
      <span class="i-rank muted">${i + 1}</span>
      <span class="i-asset">${assetChip(x.terminal)}</span>
      <span class="i-num">${fmt.int(x.launches)}</span>
      <span class="i-chg ${x.changePct == null ? "" : (x.changePct >= 0 ? "pos" : "neg")}">${x.changePct == null ? "new" : (x.changePct >= 0 ? "+" : "") + x.changePct + "%"}</span>
    </div>`).join("");
  const survRows = surv.byCategory.slice(0, 7).map(c => `
    <div class="i-row">
      <span class="i-asset">${esc(c.terminal_category)}</span>
      <span class="i-num">${fmt.int(c.total)}</span>
      <span class="i-num">${fmt.int(c.graduated)}</span>
      <span class="i-num muted">${c.total ? (c.graduated / c.total * 100).toFixed(1) + "%" : "-"}</span>
    </div>`).join("");
  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <h2 style="font-size:24px">Momentum</h2>
    <p class="muted" style="margin:0">Launches per underlying asset · last 7 days vs prior 7 days. Click an asset to see its paired tokens.</p>
    <div class="list-toolbar"><label class="list-search"><span class="sr-only">Filter momentum lists</span><input id="momentum-filter" type="search" placeholder="Filter assets or backing…" autocomplete="off"></label></div>
    <div class="insights-grid">
      <section class="d-section"><h3>Launches by asset (7d)</h3>
        <div class="i-list i-head"><span>#</span><span>Asset</span><span>Launches</span><span>Change</span></div>
        <div class="i-list preview-list" id="momentum-attention-list">${attRows}</div>
      </section>
      <section class="d-section"><h3>Survival · graduation rate by backing</h3>
        <p class="muted" style="margin:0 0 10px;font-size:13px">Overall graduation rate: ${(surv.graduationRate * 100).toFixed(1)}% (${fmt.int(surv.graduated)} of ${fmt.int(surv.total)}).</p>
        <div class="i-list i-head"><span>Backing</span><span>Tokens</span><span>Graduated</span><span>Rate</span></div>
        <div class="i-list preview-list" id="momentum-survival-list">${survRows}</div>
      </section>
    </div>
    <section class="d-section momentum-trend"><h3>Launches over time</h3><p class="muted">Observed launches by day in the selected window.</p><div class="trend-chart-wrap">${renderLaunchLineChart(att)}</div></section>
  </div>`;
  grid.querySelectorAll(".i-row[data-asset]").forEach(r => {
    const go = () => location.hash = "#/asset/" + r.dataset.asset;
    r.addEventListener("click", go);
    r.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  });
  const mf=$("#momentum-filter");
  if(mf) mf.addEventListener("input",()=>{const q=mf.value.trim().toLowerCase(); grid.querySelectorAll("#momentum-attention-list .i-row, #momentum-survival-list .i-row").forEach(r=>r.classList.toggle("filter-hidden",q && !r.textContent.toLowerCase().includes(q)));});
}

async function renderEarly() {
  beginDetail();
  grid.innerHTML = `<p class="empty" style="text-align:center;color:var(--muted);padding:60px 0">Loading…</p>`;
  const d = await api("/leaderboard/creators?limit=50");
  const rows = d.leaderboard.map((w, i) => `
    <div class="ew-row">
      <span class="i-rank muted">${i + 1}</span>
      <a class="ew-wallet" href="https://solscan.io/account/${w.creator}" target="_blank" rel="noopener" title="Open on Solscan">${shortAddr(w.creator)} ↗</a>
      <span class="ew-num">${fmt.int(w.launchCount ?? w.launches)}</span>
      <span class="ew-num pos">${fmt.int(w.graduated)}</span>
      <span class="ew-num neg">${fmt.int(w.dead)}</span>
      <span class="ew-num">${fmt.usd(w.medianPeakMarketCapUsd)}</span>
    </div>`).join("");
  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <h2 style="font-size:24px">Creator leaderboard</h2>
    <p class="muted" style="margin:0">Most active creators, ranked by launch count. Wallets open on Solscan.</p>
    <section class="d-section">
      <div class="list-toolbar"><label class="list-search"><span class="sr-only">Filter creators</span><input id="creator-filter" type="search" placeholder="Filter creator wallet…" autocomplete="off"></label></div>
      <div class="ew-head"><span>#</span><span>Wallet</span><span>Launches</span><span>Graduated</span><span>Dead</span><span>Median peak</span></div>
      <div class="ew-list preview-list" id="creator-list">${rows}</div>
      <p class="muted" style="margin:12px 0 0;font-size:12px">Top creators: launches, graduated, dead.</p>
    </section>
  </div>`;
  const cf=$("#creator-filter");
  if(cf) cf.addEventListener("input",()=>{const q=cf.value.trim().toLowerCase(); grid.querySelectorAll("#creator-list .ew-row").forEach(r=>r.classList.toggle("filter-hidden",q && !r.textContent.toLowerCase().includes(q)));});
}

const CMP_METRICS = [
  { key: "marketCapUsd", label: "Market cap", better: "high", f: n => fmt.usd(n) },
  { key: "volume24hUsd", label: "Volume 24h", better: "high", f: n => fmt.usd(n) },
  { key: "depth", label: "Depth", better: "low", f: n => (n == null ? "-" : n + " hop" + (n === 1 ? "" : "s")) },
  { key: "stackedTransferTaxBps", label: "Stacked tax", better: "low", f: n => fmt.bps(n) },
  { key: "paidOut", label: "Paid out", better: "high", f: n => fmt.tok(n) },
  { key: "holderCount", label: "Holders", better: "high", f: n => fmt.int(n) },
  { key: "launches", label: "Creator launches", better: "high", f: n => fmt.int(n) },
];

function extractMetrics(d) {
  const t = d.token, r = d.rewards, c = d.creator;
  return {
    marketCapUsd: t.market.marketCapUsd,
    volume24hUsd: t.market.volume24hUsd,
    depth: t.depth,
    stackedTransferTaxBps: t.stackedTransferTaxBps,
    paidOut: r ? r.distributedTokens : null,
    holderCount: r ? r.holderCount : null,
    launches: c ? c.launches : null,
  };
}

function isSignificant(a, b) {
  if (a == null || b == null) return false;
  const rel = Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b), 1e-9);
  return rel > 0.05;
}

function winner(a, b, better) {
  if (!isSignificant(a, b)) return { a: "", b: "" };
  const aWins = better === "high" ? a > b : a < b;
  return { a: aWins ? "▲" : "", b: aWins ? "" : "▲" };
}

function compareBody(data, other) {
  if (!data) return `<div class="muted" style="text-align:center;padding:40px 0">Pick a token</div>`;
  const t = data.token;
  const m = extractMetrics(data);
  const om = other ? extractMetrics(other) : null;
  const img = t.image_url ? `<img class="hero-img" style="width:44px;height:44px" src="${imgUrl(t.image_url)}" alt="" onerror="this.remove()">` : "";
  const rows = CMP_METRICS.map(met => {
    const mv = m[met.key], ov = om ? om[met.key] : null;
    const w = winner(mv, ov, met.better);
    return `<div class="cmp-row">
      <span class="cmp-val">${met.f(mv)}${w.a ? `<span class="cmp-win">${w.a}</span>` : ""}</span>
      <span class="cmp-metric">${met.label}</span>
      <span class="cmp-val">${w.b ? `<span class="cmp-win">${w.b}</span>` : ""}${met.f(ov)}</span>
    </div>`;
  }).join("");
  return `<div class="cmp-token">
    <div class="d-head">${img}<div><h2 style="font-size:20px">${esc(t.symbol)}</h2><p class="muted" style="font-size:12px">${esc(t.name) || ""}</p>${contractChip(t.mint)}</div></div>
    <div style="margin-top:6px">${rows}</div>
  </div>`;
}

function renderCompareBodies() {
  const a = $("#cmp-a .cmp-body");
  const b = $("#cmp-b .cmp-body");
  if (a) a.innerHTML = compareBody(cmpDate.a, cmpDate.b);
  if (b) b.innerHTML = compareBody(cmpDate.b, cmpDate.a);
}

async function loadCompareSide(side, mint) {
  const body = $(`#cmp-${side} .cmp-body`);
  body.innerHTML = `<div class="muted">Loading…</div>`;
  const d = await api(`/token/${mint}`);
  if (!d.found) { body.innerHTML = `<div class="muted">Not found.</div>`; return; }
  cmpDate[side] = d;
  renderCompareBodies();
}

function attachCompareSearch(side) {
  const input = $(`#cmp-${side} .cmp-search input`);
  const resultsEl = $(`#cmp-${side} .cmp-results`);
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { resultsEl.classList.add("hidden"); return; }
    timer = setTimeout(async () => {
      const d = await api(`/search?q=${encodeURIComponent(q)}&limit=8`);
      resultsEl.innerHTML = d.results.length
        ? d.results.map(r => `<div class="result" data-mint="${r.mint}"><img src="https://www.stonkfun.xyz/api/asset/quote-logo/${r.mint}" alt="" onerror="this.remove()"><div><span class="r-sym">${esc(r.symbol)}</span> <span class="muted">${esc(r.name) || ""}</span></div></div>`).join("")
        : `<div class="result muted" style="cursor:default">No matches.</div>`;
      resultsEl.classList.remove("hidden");
      resultsEl.querySelectorAll(".result[data-mint]").forEach(el => {
        el.addEventListener("click", () => {
          resultsEl.classList.add("hidden");
          input.value = el.dataset.mint ? "" : input.value;
          if (side === "a") compareA = el.dataset.mint; else compareB = el.dataset.mint;
          loadCompareSide(side, el.dataset.mint);
        });
      });
    }, 180);
  });
}

async function renderCompare() {
  beginDetail();
  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <h2 style="font-size:24px">Compare tokens</h2>
    <div class="cmp-grid">
      <div class="cmp-panel" id="cmp-a">
        <div class="cmp-search"><input type="search" placeholder="Search token…" autocomplete="off"><div class="cmp-results results hidden"></div></div>
        <div class="cmp-body"><div class="muted" style="text-align:center;padding:40px 0">Pick a token</div></div>
      </div>
      <div class="cmp-panel" id="cmp-b">
        <div class="cmp-search"><input type="search" placeholder="Search token…" autocomplete="off"><div class="cmp-results results hidden"></div></div>
        <div class="cmp-body"><div class="muted" style="text-align:center;padding:40px 0">Pick a token</div></div>
      </div>
    </div>
  </div>`;
  attachCompareSearch("a");
  attachCompareSearch("b");
  if (compareA) loadCompareSide("a", compareA);
  if (compareB) loadCompareSide("b", compareB);
}

async function loadTicker() {
  try {
    const [tickerData, attentionData, assetsData] = await Promise.all([api("/ticker"), api("/attention?days=7"), api("/assets?limit=100")]);
    const attention = new Map((attentionData.assets || []).map(x => [String(x.terminal || "").toUpperCase(), x]));
    const assets = new Map((assetsData.assets || []).map(x => [String(x.symbol || "").toUpperCase(), x]));
    const items = tickerData.ticker.map(x => {
      const symbol = String(x.symbol || "").toUpperCase();
      const a = attention.get(symbol);
      const asset = assets.get(symbol);
      const trend = a && a.changePct != null ? `<span class="t-trend ${a.changePct >= 0 ? "pos" : "neg"}">${fmt.pct(a.changePct)} <small>7d launches</small></span>` : "";
      const mc = asset && asset.totalMarketCapUsd != null ? `<span class="t-mc">MC ${fmt.usd(asset.totalMarketCapUsd)}</span>` : "";
      return `<span class="tick">${assetChip(x.symbol || x.ticker)}<span class="t-sym">${esc(x.ticker)}</span><span class="t-price">${fmt.stock(x.priceUsd)}</span>${mc}<span class="t-share">${fmt.pct(x.sharePct)} tokens</span>${trend}</span>`;
    }).join("");
    tickerTrack.innerHTML = items + items;
  } catch (e) {
    ticker.classList.add("hidden");
  }
}

function renderLive() {
  beginDetail();
  grid.innerHTML = `<div class="detail-inner">
    ${backBtn()}
    <h2 style="font-size:24px">Live Date</h2>
    <p class="muted" style="margin:0">Onchain data via API and MCP. Updated every 15 minutes.</p>

    <section class="d-section">
      <h3>1 · Connect an AI agent</h3>
      <p class="muted" style="font-size:13px;margin:0 0 10px">Claude, Cursor and Gemini read the same engine as the web. Add the server once, then ask in natural language.</p>
      <pre class="mono" style="background:var(--surface-2);padding:14px;border-radius:10px;overflow-x:auto;margin:0;white-space:pre-wrap;word-break:break-word">{"mcpServers": {"sdb": {"command": "python",
  "args": ["/path/to/mcp_server.py"],
  "env": {"SDB_API_URL": "https://solanastockdatabase.com"}}}}</pre>
    </section>

    <section class="d-section">
      <h3>2 · Get a key for real-time</h3>
      <div class="m-grid">
        ${metric("Free", "$0", "30 req/min · 15-min cycle only")}
        ${metric("Starter", "$5/mo", "9,000 req/mo · on-demand refresh")}
        ${metric("Trader", "$50/mo", "100,000 req/mo · full real-time")}
      </div>
      <p class="muted" style="font-size:13px;margin-top:10px">Add the key as <code>SDB_API_KEY</code> in the config above. Free stays on the snapshot; paid tiers trigger RPC on demand.</p>
    </section>

    <section class="d-section">
      <h3>3 · Ask</h3>
      <p class="mono" style="margin:0">"top 10 stock tokens today" · "how much token X paid out in NVIDIA" · "who launched Y" · "compare Z with W"</p>
    </section>
  </div>`;
}

function renderSystemStats(d) {
  const el=$("#system-stats"); if(!el)return;
  const since=d.firstSnapshotAt ? `Desde ${fmt.date(d.firstSnapshotAt)}` : "Desde o primeiro ciclo";
  el.innerHTML=`<div class="system-lead"><strong>${fmt.int(d.snapshotCycles||0)}</strong><span>data cycles</span><small>${since}</small></div><div class="system-stat"><strong>${fmt.int(d.tokenCount||0)}</strong><span>tokens</span></div><div class="system-stat"><strong>${fmt.int(d.rewardCoins||0)}</strong><span>reward coins</span></div><div class="system-stat"><strong>${fmt.int(d.creators||0)}</strong><span>creators</span></div>`;
}
function yieldRow(x,i){return `<a class="yield-row" href="#/token/${encodeURIComponent(x.mint)}"><span class="yield-rank">${i+1}</span><span class="yield-token">${tokenIcon(x.mint,x.symbol,x.imageUrl,"token-icon list-token-icon")}<span><strong>${esc(x.symbol||shortAddr(x.mint))}</strong><small>${esc(x.name||"")}</small></span></span>${assetChip(x.terminal)}<span class="yield-value">${fmt.tok(Number(x.distributedTokens)||0)} <small>units</small></span><span class="yield-meta">${fmt.int(x.payoutCount)} payouts</span></a>`;}
async function loadYieldFeatured(category="xstock") { const el=$("#yield-featured"); if(!el)return; el.innerHTML='<div class="featured-loading">Loading yield leaderboard…</div>'; try{const d=await api(`/leaderboard/rendimento?category=${encodeURIComponent(category)}&limit=20`); const rows=d.leaderboard||[]; el.innerHTML=`<div class="featured-head"><div><h2 id="yield-title">Top stock payouts</h2><p class="muted">Units distributed in the latest indexed cycle.</p></div><div class="featured-tabs"><input class="list-filter" data-filter-target="yield-table" placeholder="Filter…" aria-label="Filter payouts"><button class="active" data-yield-category="xstock">xStock</button><button data-yield-category="prestock">PreStock</button></div></div><div class="yield-table">${rows.length?rows.slice(0,7).map(yieldRow).join(""):'<p class="muted featured-empty">No payouts found in this category.</p>'}</div>`; el.querySelectorAll("[data-yield-category]").forEach(b=>b.addEventListener("click",()=>loadYieldFeatured(b.dataset.yieldCategory)));wireListFilters();}catch(e){el.innerHTML='<p class="muted featured-empty">Leaderboard temporarily unavailable.</p>';}}
async function loadAttentionFeatured(){const el=$("#attention-featured");if(!el)return;try{const d=await api("/attention?days=7"), rows=(d.assets||[]).slice(0,7), max=Math.max(1,...rows.map(x=>Number(x.launches)||0));el.innerHTML=`<div class="featured-head"><div><span class="section-kicker">Momentum</span><h2 id="attention-title">Stocks in focus</h2><p class="muted">The most active underlying assets in the last ${d.windowDays||7} days.</p></div><input class="list-filter" data-filter-target="attention-list" placeholder="Filter assets" aria-label="Filter attention list"></div><div class="attention-list" id="attention-list">${rows.length?rows.map((x,i)=>`<a class="attention-row" href="#/asset/${encodeURIComponent(x.terminal)}"><span class="attention-rank">${String(i+1).padStart(2,"0")}</span><div class="attention-asset">${assetChip(x.terminal)}<span class="attention-bar"><i style="width:${Math.max(4,(Number(x.launches)||0)/max*100)}%"></i></span></div><strong class="attention-count">${fmt.int(x.launches)}<small> launches</small></strong><span class="attention-change ${x.changePct!=null&&x.changePct<0?'neg':'pos'}">${x.changePct==null?'new':fmt.pct(x.changePct)}<small> 7d</small></span></a>`).join(""):'<p class="muted featured-empty">No attention data yet.</p>'}</div>`;wireListFilters();}catch(e){el.innerHTML='<p class="muted featured-empty">Attention data temporarily unavailable.</p>';}}
async function loadDbcFeatured(){const el=$("#dbc-featured");if(!el)return;el.innerHTML='<div class="featured-loading">Loading Meteora DBC coverage…</div>';try{const [summary,pools]=await Promise.all([api("/dbc/summary"),api("/dbc/pools?limit=7")]);const rows=pools.pools||[];const st=summary.stats||{};const fresh=summary.freshness||{};const quoteRows=(summary.quotes||[]).map(q=>`<span class="dbc-quote-card">${assetChip(q.symbol||"DBC")}<strong>${fmt.int(q.configs||0)}</strong><small>configs</small></span>`).join("");el.innerHTML=`<div class="featured-head"><div><span class="section-kicker">Onchain launch infrastructure</span><h2 id="dbc-title">Meteora DBC Launch Passport</h2><p class="dbc-note">Readable evidence of stock-quoted Dynamic Bonding Curve launches indexed by SDB from a bounded RPC capture.</p></div><a class="quiet-link" href="#/docs">Methodology ↗</a></div><div class="dbc-hero-stats"><div><strong>${fmt.int(st.pools||0)}</strong><span>pools indexed</span></div><div><strong>${fmt.int(st.configs||0)}</strong><span>configs indexed</span></div><div><strong>${fmt.int(st.byStatus&&st.byStatus.active||0)}</strong><span>active curves</span></div><div><strong>${fmt.int(st.byStatus&&st.byStatus.migrated||0)}</strong><span>migrated</span></div><div><strong>${fmt.int(st.rpcRequests||0)}</strong><span>RPC requests</span></div></div><div class="dbc-evidence"><span>Latest capture: ${esc(fresh.capturedAt||"-")}</span><span>Slot: ${esc(fresh.slot||"-")}</span><span>Run ${esc(String(fresh.runId||"-"))}</span></div><div class="dbc-quotes"><h3>Stock quote coverage</h3><div class="dbc-quote-grid">${quoteRows||'<span class="muted">No quote assets indexed.</span>'}</div></div><div class="dbc-list-head"><h3>Recent indexed curves</h3><span class="muted">Pool · config · quote · state</span></div><div class="dbc-list">${rows.length?rows.map((x,i)=>`<article class="dbc-row"><div class="dbc-rank">${String(i+1).padStart(2,"0")}</div><a class="dbc-token" href="#/token/${encodeURIComponent(x.baseMint)}">${tokenIcon(x.baseMint,x.tokenSymbol,x.tokenImageUrl,"token-icon dbc-token-icon")}<span><strong>${esc(x.tokenSymbol||shortAddr(x.baseMint))}</strong><small>${esc(x.tokenName||"Base token")}</small><code>${esc(shortAddr(x.baseMint))}</code></span></a><div class="dbc-quote">${assetChip(x.quoteSymbol||"DBC")}<small>${esc(x.variant||"VirtualPool")}</small></div><div class="dbc-state"><strong>${esc(x.status||"indexed")}</strong><small>${esc(x.curveProgress||"0")} curve progress</small></div><div class="dbc-addresses"><a href="https://solscan.io/account/${encodeURIComponent(x.address)}" target="_blank" rel="noopener noreferrer">Pool ${esc(shortAddr(x.address))} ↗</a><a href="https://solscan.io/account/${encodeURIComponent(x.configAddress)}" target="_blank" rel="noopener noreferrer">Config ${esc(shortAddr(x.configAddress))} ↗</a></div></article>`).join(""):'<p class="muted featured-empty">No DBC pools available.</p>'}</div>`;}catch(e){el.innerHTML='<p class="muted featured-empty">Meteora DBC data temporarily unavailable.</p>';}}
async function loadCreatorsFeatured(){const el=$("#creators-featured");if(!el)return;try{const d=await api("/leaderboard/creators?limit=10"), rows=(d.leaderboard||[]).slice(0,7);el.innerHTML=`<div class="featured-head"><div><span class="section-kicker">Wallet activity</span><h2 id="creators-title">Featured creators</h2><p class="muted">Creators ranked by indexed launches. Curated identities appear only when sourced.</p></div><a class="quiet-link" href="#/creators">View full ranking ↗</a><input class="list-filter" data-filter-target="creator-list" placeholder="Filter wallets" aria-label="Filter creators"></div><div class="creator-list" id="creator-list">${rows.length?rows.map((x,i)=>{const total=(x.graduated||0)+(x.dead||0)+(x.live||0), cls=x.graduated>0?'good':(total&&x.dead/total>.8?'warn':'neutral');return `<a class="creator-row" data-creator="${esc(x.creator)}" href="#/creators"><span class="creator-rank">${String(i+1).padStart(2,"0")}</span><span class="creator-status ${cls}">${x.graduated>0?'▲':x.dead&&total&&x.dead/total>.8?'!':'·'}</span>${walletIdentityHtml(x.creator,true)}<span class="creator-stat"><strong>${fmt.int(x.launchCount??x.launches)}</strong><small> launches</small></span><span class="creator-stat"><strong>${fmt.int(x.graduated)}</strong><small> graduated</small></span><strong class="creator-peak">${fmt.usd(x.medianPeakMarketCapUsd)}<small> median peak</small></strong></a>`}).join(""):'<p class="muted featured-empty">Not enough creator data yet.</p>'}</div>`;wireListFilters();}catch(e){el.innerHTML='<p class="muted featured-empty">Creator data temporarily unavailable.</p>';}}
async function showCreatorModal(addr){const backdrop=$("#creator-modal-backdrop"), content=$("#creator-modal-content");if(!backdrop||!content)return;backdrop.classList.add("open");backdrop.setAttribute("aria-hidden","false");content.innerHTML='<p class="muted">Loading creator portfolio…</p>';try{const d=await api(`/creator/${encodeURIComponent(addr)}/tokens?limit=60`), rows=d.tokens||[];const byAsset={};rows.forEach(t=>{const key=t.terminal_symbol||t.terminal||"Unknown";byAsset[key]=(byAsset[key]||0)+1;});const assetSummary=Object.entries(byAsset).slice(0,12).map(([k,v])=>`<span class="creator-holding">${assetChip(k)} <strong>${fmt.int(v)}</strong><small> tokens</small></span>`).join("");content.innerHTML=`<div class="creator-modal-head"><span class="section-kicker">Indexed creator portfolio</span><h2 id="creator-modal-title">${walletIdentityHtml(addr)}</h2><p class="mono">${esc(addr)}</p><p class="muted">Launches linked to this wallet.</p></div><div class="creator-modal-stats"><div><strong>${fmt.int(rows.length)}</strong><small>indexed tokens</small></div><div><strong>${fmt.int(Object.keys(byAsset).length)}</strong><small>stock assets</small></div></div><div class="creator-holdings"><h3>Stock exposure by indexed tokens</h3><div class="creator-holding-grid">${assetSummary||'<span class="muted">No underlying asset data.</span>'}</div></div><div class="creator-portfolio-list">${rows.slice(0,60).map(t=>`<a class="creator-portfolio-row" href="#/token/${encodeURIComponent(t.mint)}"><span>${tokenIcon(t.mint,t.symbol,t.image_url,"token-icon list-token-icon")}</span><span><strong>${esc(t.symbol||shortAddr(t.mint))}</strong><small>${esc(t.name||"")}</small></span><span>${assetChip(t.terminal_symbol||t.terminal||"Unknown")}</span><strong>${fmt.usd(t.market_cap_usd ?? t.marketCapUsd)}</strong></a>`).join("")||'<p class="muted">No tokens found.</p>'}</div>`;}catch(e){content.innerHTML='<p class="muted">Creator portfolio temporarily unavailable.</p>';}}
function closeCreatorModal(){const b=$("#creator-modal-backdrop");if(b){b.classList.remove("open");b.setAttribute("aria-hidden","true");}}
function wireListFilters(){document.querySelectorAll(".list-filter").forEach(i=>{if(i.dataset.wired)return;i.dataset.wired="1";i.addEventListener("input",()=>{const q=i.value.toLowerCase().trim();const box=document.querySelector("."+i.dataset.filterTarget);if(box)box.querySelectorAll(":scope > *").forEach(r=>r.classList.toggle("filter-hidden",q&&!r.textContent.toLowerCase().includes(q)));});});}
async function loadQuoteCaps(){try{const d=await api("/quote-market-caps");const caps=d.quotes||{};document.querySelectorAll(".asset-cap-badge").forEach(el=>{const crypto=el.querySelector(".cap-crypto"), stock=el.querySelector(".cap-stock");const q=crypto?.dataset.quote, data=caps[q]||caps[q?.toUpperCase()];if(crypto)crypto.textContent=data?.cryptoMarketCapUsd!=null?fmt.usd(data.cryptoMarketCapUsd):"Not indexed";const signal=data?.stock;if(stock)stock.textContent=signal?.priceUsd!=null?`${fmt.stock(signal.priceUsd)} · ${signal.sharePct??"-"}% share`:signal?.sharePct!=null?`${signal.sharePct}% share`:"No signal";});}catch(e){document.querySelectorAll(".cap-stock,.cap-crypto").forEach(el=>{el.textContent="Unavailable";});}}
function loadHomeFeatured(){Promise.all([api("/stats").then(renderSystemStats).catch(()=>{}),loadYieldFeatured(),loadAttentionFeatured(),loadDbcFeatured(),loadCreatorsFeatured(),loadYieldCalc(),loadHomeCompare()]).then(loadQuoteCaps);}

function renderLanding() {
  state.homeOnly = true; state.detail = false;
  if (homeFeatured) homeFeatured.classList.remove("hidden");
  if (homeBento) homeBento.classList.remove("hidden");
  ticker.classList.remove("hidden");
  menuBtn.classList.remove("hidden");
  sentinel.classList.remove("hidden");
  $(".fade-bottom").classList.remove("hidden");
  grid.className = "grid";
  grid.setAttribute("role", "list");
  grid.setAttribute("aria-label", "Token list");
  resetAndLoad();
  loadHomeFeatured();
}

function renderDocs(){
  beginDetail();
  const mcpConfig = JSON.stringify({mcpServers:{sdb:{command:"python",args:["/path/to/mcp_server.py"],env:{SDB_API_URL:"https://solanastockdatabase.com"}}}}, null, 2);
  const tools = [
    ["search_tokens", "Search by name, symbol, or mint", "q, limit"], ["get_token", "Backing, yield, creator, and onchain data", "mint"],
    ["get_creator", "Indexed creator history", "creator"], ["list_assets", "Underlying asset coverage", "none"],
    ["get_attention", "Launch activity by underlying asset", "days"], ["get_survival", "Graduation and survival metrics", "none"],
    ["leaderboard_rendimento", "Tokens ranked by distributed units", "category, limit"], ["get_stats", "System and snapshot counts", "none"]
  ];
  grid.innerHTML = `<div class="detail-inner docs-page">
    <button class="back" onclick="location.hash=''">Back</button>
    <p class="eyebrow">Builder documentation</p><h2>Build on the same data engine</h2>
    <p class="muted docs-lead">Read-only data via REST and MCP.</p>
    <section class="docs-card docs-quick"><h3>REST quick start</h3><pre class="docs-code">curl https://solanastockdatabase.com/api/stats</pre><button class="quiet-button" data-copy-doc="curl https://solanastockdatabase.com/api/stats">Copy command</button><p class="muted">Free access: no key, latest indexed cycle, 30 requests per minute.</p></section>
    <div class="docs-grid">
      <section class="docs-card"><h3>Core REST endpoints</h3><p><code>GET /api/stats</code><br><code>GET /api/search?q=NVDA</code><br><code>GET /api/token/{mint}</code><br><code>GET /api/cards</code><br><code>GET /api/attention?days=7</code><br><code>GET /api/leaderboard/rendimento</code><br><code>GET /api/leaderboard/creators</code><br><code>GET /api/dbc/summary</code></p></section>
      <section class="docs-card"><h3>MCP setup</h3><p>Download the inspectable stdio client, then point your MCP host at the public API.</p><pre class="docs-code">curl -O https://solanastockdatabase.com/mcp</pre><pre class="docs-code">${esc(mcpConfig)}</pre><button class="quiet-button" data-copy-doc="${esc(mcpConfig)}">Copy config</button></section>
      <section class="docs-card"><h3>Eight MCP tools</h3><div class="docs-tools">${tools.map(t=>`<div class="docs-tool"><code>${t[0]}</code><span>${t[1]}</span><small>${t[2]}</small></div>`).join("")}</div></section>
      <section class="docs-card"><h3>Data and methodology</h3><p>StonkFun every 15 minutes. Onchain via Helius. No buy or sell signals.</p><a class="quiet-link" href="#/live">See connection guide ↗</a></section>
      <section class="docs-card"><h3>Plans and limits</h3><p><strong>Free · $0</strong><br>Database-only snapshots, 30 req/min.</p><p><strong>Starter · $5/mo</strong><br>9,000 requests, on-demand refresh.</p><p><strong>Trader · $50/mo</strong><br>100,000 requests, full real-time access.</p></section>
      <section class="docs-card"><h3>Stable contract</h3><p>Responses are JSON objects. MCP returns the same response data as its REST counterpart. Paid refresh is <code>GET /api/token/{mint}/refresh</code> with a Starter or Trader bearer key.</p></section>
    </div>
  </div>`;
  grid.querySelectorAll("[data-copy-doc]").forEach(b=>b.addEventListener("click",()=>copyText(b.dataset.copyDoc,b)));
}

function syncNav() {
  const h = location.hash;
  $$("#site-nav a").forEach(a => {
    const nav = a.dataset.nav;
    let active = false;
    if (nav === "home") active = h === "" || h === "#";
    else if (nav === "momentum") active = h === "#/momentum" || h === "#/insights";
    else if (nav === "creators") active = h === "#/creators" || h === "#/early";
    else if (nav === "compare") active = h === "#/compare";
    else if (nav === "live") active = h === "#/live";
    else if (nav === "docs") active = h === "#/docs";
    a.classList.toggle("active", active);
  });
}

function route() {
  syncNav();
  let m = location.hash.match(/^#\/token\/(.+)$/);
  if (m) { renderToken(decodeURIComponent(m[1])); return; }
  m = location.hash.match(/^#\/asset\/(.+)$/);
  if (m) { renderAsset(decodeURIComponent(m[1])); return; }
  if (location.hash === "#/momentum" || location.hash === "#/insights") { renderInsights(); return; }
  if (location.hash === "#/creators" || location.hash === "#/early") { renderEarly(); return; }
  if (location.hash === "#/docs") { renderDocs(); return; }
  if (location.hash === "#/live") { renderLive(); return; }
  if (location.hash === "#/compare") { renderCompare(); return; }
  renderLanding();
}

let searchTimer = null;
const searchInput = $("#search");
const searchResults = $("#search-results");

function closeSearch() { searchResults.classList.add("hidden"); }

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (!q) { closeSearch(); return; }
  searchTimer = setTimeout(async () => {
    const d = await api(`/search?q=${encodeURIComponent(q)}&limit=12`);
    let html = "";
    if (d.assets && d.assets.length) {
      html += d.assets.map(a => `
        <div class="result" data-asset="${esc(a.terminal_symbol)}" role="option" tabindex="0">
          <div class="asset-ico">${esc(a.terminal_symbol.slice(0, 2))}</div>
          <div><div><span class="r-sym">${esc(a.terminal_symbol)}</span> <span class="muted">underlying asset</span></div>
          <div class="r-meta">${a.c} tokens backed</div></div>
        </div>`).join("");
    }
    html += d.results.map(r => `
      <div class="result" role="option" data-mint="${r.mint}" tabindex="0">
        <img src="https://www.stonkfun.xyz/api/asset/quote-logo/${r.mint}" alt="" onerror="this.remove()">
        <div><div><span class="r-sym">${esc(r.symbol)}</span> <span class="muted">${esc(r.name) || ""}</span></div>
        <div class="r-meta">MC ${fmt.usd(r.market_cap_usd)} · depth ${r.depth}</div></div>
      </div>`).join("");
    if (!html) html = `<div class="result muted" style="cursor:default">No matches.</div>`;
    searchResults.innerHTML = html;
    searchResults.classList.remove("hidden");
    $$("#search-results .result[data-mint]").forEach(el => {
      const go = () => { closeSearch(); searchInput.value = ""; location.hash = "#/token/" + el.dataset.mint; };
      el.addEventListener("click", go);
      el.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    });
    $$("#search-results .result[data-asset]").forEach(el => {
      const go = () => { closeSearch(); searchInput.value = ""; location.hash = "#/asset/" + el.dataset.asset; };
      el.addEventListener("click", go);
      el.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    });
  }, 180);
});

document.addEventListener("click", e => {
  if (!e.target.closest(".search-wrap")) closeSearch();
  const chip = e.target.closest(".contract");
  if (chip) copyText(chip.dataset.copy, chip);
  const card = e.target.closest(".card[data-mint]");
  if (card && !e.target.closest(".contract")) location.hash = "#/token/" + card.dataset.mint;
  const creator = e.target.closest(".creator-row[data-creator]");
  if (creator) { e.preventDefault(); showCreatorModal(creator.dataset.creator); }
});
searchInput.addEventListener("keydown", e => {
  if (e.key === "Escape") closeSearch();
});

menuBtn.addEventListener("click", openDrawer);
$("#drawer-close").addEventListener("click", closeDrawer);
backdrop.addEventListener("click", closeDrawer);
$("#theme-btn").addEventListener("click", cycleTheme);
$("#creator-modal-close").addEventListener("click", closeCreatorModal);
$("#creator-modal-backdrop").addEventListener("click", e => { if (e.target.id === "creator-modal-backdrop") closeCreatorModal(); });
$("#apply-btn").addEventListener("click", applyDraft);

$$("[data-range]").forEach(b => b.addEventListener("click", () => setRange(b.dataset.range)));
$$("[data-sort]").forEach(b => b.addEventListener("click", () => setDraftSort(b.dataset.sort)));
$$("[data-stat]").forEach(b => b.addEventListener("click", () => toggleStat(b.dataset.stat)));

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
  if (e.key === "Escape" && $("#creator-modal-backdrop").classList.contains("open")) closeCreatorModal();
  if (e.key === "/" && document.activeElement !== searchInput &&
      !/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "")) {
    e.preventDefault();
    searchInput.focus();
  }
});

drawer.addEventListener("keydown", e => {
  if (e.key !== "Tab") return;
  const focusables = $$("button, [tabindex]", drawer).filter(el => el.offsetParent !== null);
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state.theme === "auto") applyTheme();
});

api("/stats").then(s => {
  const k = Math.floor(s.tokenCount / 1000) * 1000;
  hint.textContent = `Search across ${k.toLocaleString("en-US")}+ tokens`;
});

const TIP_PROMPTS = [
  "top 10 stock tokens today",
  "how much token X paid out in NVIDIA",
  "who launched token Y",
  "compare Z with W",
  "which memstocks paid out the most this week",
  "which asset is trending in launches",
  "stacked tax of token X",
  "how many tokens are backed by Tesla",
  "show the holders of token Y",
  "onchain events of token Z",
];
(function rotateTip() {
  const tip = $("#search-tip");
  const em = tip ? tip.querySelector("em") : null;
  if (!tip || !em) return;
  let i = 0;
  setInterval(() => {
    i = (i + 1) % TIP_PROMPTS.length;
    tip.style.opacity = "0";
    setTimeout(() => {
      em.textContent = `Hint: ask "${TIP_PROMPTS[i]}" from Claude, Cursor or Gemini via the sdb MCP.`;
      tip.style.opacity = "1";
    }, 300);
  }, 4200);
})();

applyTheme();
loadTicker();
window.addEventListener("hashchange", route);
route();

/* ---- Home: Yield calculator ---- */
async function loadYieldCalc(){
  const box=$("#yield-calc"); if(!box) return;
  box.innerHTML='<div class="muted" style="padding:8px 0">Loading…</div>';
  let rows=[];
  try{ const d=await api("/leaderboard/rendimento?category=xstock&limit=20"); rows=d.leaderboard||[]; }catch(e){}
  if(!rows.length){ box.innerHTML='<p class="muted featured-empty">Calculator unavailable.</p>'; return; }
  box.innerHTML=`
    <div class="calc-grid">
      <div class="calc-field"><label>Reward coin</label><select id="yc-token">${rows.map(r=>`<option value="${esc(r.mint)}">${esc(r.symbol||shortAddr(r.mint))} · ${esc(r.terminal||"")}</option>`).join("")}</select></div>
      <div class="calc-field"><label>Amount held (USD)</label><input id="yc-amount" class="num" inputmode="numeric" value="1000"></div>
    </div>
    <div class="calc-out">
      <div class="cell"><div class="k">Est. income / year</div><div class="v big" id="yc-year">-</div><div class="s" id="yc-apr">-</div></div>
      <div class="cell"><div class="k">Est. income / month</div><div class="v" id="yc-month">-</div><div class="s" id="yc-note2"></div></div>
    </div>
    <p class="calc-foot">Estimate from current 24h volume. Reward coins only.</p>`;
  const sel=$("#yc-token"), amt=$("#yc-amount"), cache={};
  async function calc(){
    const mint=sel.value, amount=Math.max(0,parseFloat(amt.value)||0);
    let d=cache[mint]; if(d===undefined||d===null){ try{ d=await api(`/token/${mint}`);}catch(e){ d=null; } cache[mint]=d; }
    const yEl=$("#yc-year"),mEl=$("#yc-month"),aEl=$("#yc-apr"),n2=$("#yc-note2");
    if(!d||!d.found||!d.token){ yEl.textContent="-"; mEl.textContent="-"; aEl.textContent="no data"; if(n2)n2.textContent=""; return; }
    const t=d.token, vol=(t.market&&t.market.volume24hUsd)||0, mc=(t.market&&t.market.marketCapUsd)||0, taxBps=t.stackedTransferTaxBps||0;
    if(!taxBps){ yEl.textContent="$0"; mEl.textContent="$0"; aEl.textContent="no transfer-fee rewards"; n2.textContent=""; return; }
    const apr= mc>0 ? (vol*365)*(taxBps/10000)/mc : 0, year=amount*apr, month=year/12;
    yEl.textContent=fmt.usd(year); mEl.textContent=fmt.usd(month);
    aEl.textContent="Implied APR ~"+(apr*100).toFixed(apr>=0.1?0:1)+"%";
    n2.textContent="in "+((t.terminal&&t.terminal.symbol)||"stock")+" rewards";
  }
  sel.addEventListener("change",calc); amt.addEventListener("input",calc); calc();
}

/* ---- Home: Token comparator ---- */
async function loadHomeCompare(){
  const box=$("#home-compare"); if(!box) return;
  box.innerHTML='<div class="muted" style="padding:8px 0">Loading…</div>';
  let list=[];
  try{ const d=await api("/cards?range=ALL&sort=mc&limit=12&offset=0"); list=d.cards||[]; }catch(e){}
  if(list.length<2){ box.innerHTML='<p class="muted featured-empty">Comparator unavailable.</p>'; return; }
  const opts=list.map(c=>`<option value="${esc(c.mint)}">${esc(c.symbol||shortAddr(c.mint))}</option>`).join("");
  box.innerHTML=`<div class="hc-pickers"><select id="hc-a">${opts}</select><span class="vs">VS</span><select id="hc-b">${opts}</select></div><div id="hc-body"></div>`;
  const A=$("#hc-a"),B=$("#hc-b"),cache={};
  A.value=list[0].mint; B.value=list[Math.min(2,list.length-1)].mint;
  async function get(mint){ if(cache[mint]!==undefined)return cache[mint]; let d=null; try{ d=await api(`/token/${mint}`);}catch(e){} cache[mint]=d; return d; }
  async function draw(){
    const body=$("#hc-body"); if(body) body.innerHTML='<div class="muted" style="padding:14px 0">Loading…</div>';
    const [da,db]=await Promise.all([get(A.value),get(B.value)]);
    if(!body) return;
    if(!da||!da.found||!db||!db.found){ body.innerHTML='<p class="muted">Data unavailable.</p>'; return; }
    const ma=extractMetrics(da), mb=extractMetrics(db);
    body.innerHTML=CMP_METRICS.map(met=>{
      const va=ma[met.key],vb=mb[met.key],w=winner(va,vb,met.better);
      return `<div class="cmp-row"><span class="cmp-val">${met.f(va)}${w.a?`<span class="cmp-win">${w.a}</span>`:""}</span><span class="cmp-metric">${met.label}</span><span class="cmp-val">${w.b?`<span class="cmp-win">${w.b}</span>`:""}${met.f(vb)}</span></div>`;
    }).join("");
  }
  A.addEventListener("change",draw); B.addEventListener("change",draw); draw();
}
