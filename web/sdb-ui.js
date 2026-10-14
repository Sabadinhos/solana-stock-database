/* SDB UI: JSON spec -> DOM, sem framework.
   SDB.render(container, specs) desenha e reaproveita nos por chave.
   SDB.mapToken(raw, opts) converte a resposta da API em spec.
   Classes seguem sdb-ui.css: card, row, creator, avatar, pad, trend. */

(function (global) {
  'use strict';

  /* ---------- DOM ---------- */

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v);
      }
    }
    if (children) {
      for (var i = 0; i < children.length; i++) {
        var c = children[i];
        if (c === null || c === undefined || c === false) continue;
        node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      }
    }
    return node;
  }

  function svg(tag, attrs, children) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (children) children.forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function setText(node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  }

  /* ---------- catalogo ---------- */

  var ASSETS = {
    NVDAx:{color:'#4DD8FF',mono:'NV',logo:'https://cdn.simpleicons.org/nvidia'}, SPYx:{color:'#F2D544',mono:'SP',logo:null},
    TSLAx:{color:'#FF6F91',mono:'TS',logo:'https://cdn.simpleicons.org/tesla'}, GMEx:{color:'#F08A3C',mono:'GM',logo:'https://cdn.simpleicons.org/gamejolt'},
    HOODx:{color:'#9A7BFF',mono:'HD',logo:'https://cdn.simpleicons.org/robinhood'}, MSTRx:{color:'#6C8CFF',mono:'MS',logo:'https://cdn.simpleicons.org/microstrategy'},
    AAPLx:{color:'#B8C0CC',mono:'AA',logo:'https://cdn.simpleicons.org/apple'}, COINx:{color:'#00C2A8',mono:'CO',logo:'https://cdn.simpleicons.org/coinbase'},
    OPENAIx:{color:'#E36FC8',mono:'OA',logo:'https://cdn.simpleicons.org/openai'}, ANTHROPICx:{color:'#D97757',mono:'AN',logo:'https://cdn.simpleicons.org/anthropic'}
  };
  var ASSET_ALIASES = {NVDA:'NVDAx',NVDAX:'NVDAx',SPY:'SPYx',SPYX:'SPYx',TSLA:'TSLAx',TSLAX:'TSLAx',GME:'GMEx',GMEX:'GMEx',HOOD:'HOODx',HOODX:'HOODx',MSTR:'MSTRx',MSTRX:'MSTRx',AAPL:'AAPLx',AAPLX:'AAPLx',COIN:'COINx',COINX:'COINx',OPENAI:'OPENAIx',OPENAIX:'OPENAIx',ANTHROPIC:'ANTHROPICx',ANTHROPICX:'ANTHROPICx'};

  var LAUNCHPADS = {
    stonkfun: { label: 'SF', name: 'StonkFun',    icon: null },
    meteora:  { label: 'MT', name: 'Meteora DBC', icon: null },
    pumpfun:  { label: 'PF', name: 'Pump.fun',    icon: null }
  };

  function assetMeta(ticker) {
    var raw = String(ticker || '').trim(), key = ASSET_ALIASES[raw.toUpperCase()] || raw;
    if (ASSETS[key]) return ASSETS[key];
    return { color:'#8C8C8C', mono:raw.replace(/[^A-Za-z]/g,'').slice(0,2).toUpperCase() || '??', logo:null };
  }

  /* Avatar: imagem quando existe, monograma quando nao. O monograma e estado final,
     nao placeholder: se a logo faltar, a interface continua legivel. */
  function avatar(ticker, size, imageUrl) {
    var meta = assetMeta(ticker);
    var box = el('span', {
      class: 'avatar avatar--' + (size || 'md'),
      style: '--asset: ' + meta.color,
      title: ticker || 'unknown asset'
    }, [el('span', { class: 'avatar__mono', text: meta.mono })]);
    var source = imageUrl || meta.logo;
    if (source) { var img = el('img', { class:'avatar__img', src:source, alt:(ticker || '') + ' logo', loading:'lazy', decoding:'async', referrerpolicy:'no-referrer' }); img.addEventListener('load', function(){ box.classList.add('has-logo'); }); img.addEventListener('error', function(){ img.remove(); box.classList.remove('has-logo'); }); box.appendChild(img); if(img.complete&&img.naturalWidth>0)box.classList.add('has-logo'); }
    return box;
  }

  function iconMark(label, color, small) {
    var mark = svg('svg', { class: small ? 'icon-mark icon-mark--small' : 'icon-mark', viewBox: '0 0 32 32', width: small ? '16' : '32', height: small ? '16' : '32', 'aria-hidden': 'true' }, [
      svg('circle', { cx: '16', cy: '16', r: small ? '14' : '15', fill: 'none', stroke: color || 'currentColor', 'stroke-width': '1.5' }),
      svg('path', { d: 'M9 20.5h14M11 16h10M13 11.5h6', stroke: color || 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' })
    ]);
    mark.setAttribute('data-label', label || '--');
    return mark;
  }

  function launchpadIcon(id) {
    var pad = LAUNCHPADS[id];
    var box = el('span', { class: 'pad', title: pad ? pad.name : 'unknown launchpad' },
      [el('span', { class: 'pad__mono', text: pad ? pad.label : '--' })]);
    box.appendChild(iconMark(pad ? pad.label : '--', 'currentColor', true));
    return box;
  }

  /* Triangulo direcional so existe com variacao real E janela de tempo explicita.
     Sem valor ou sem janela nao ha marca: tendencia nunca e inventada. */
  function changeMark(value, windowLabel, subject) {
    var n = (value === null || value === undefined || value === '') ? NaN : Number(value);
    if (!isFinite(n) || !windowLabel) return null;
    var dir = n > 0 ? 'up' : (n < 0 ? 'down' : 'flat');
    var text = (n > 0 ? '+' : '') + n.toFixed(1) + '%';
    return el('span', { class: 'change change--' + dir, title: (subject || 'Change') + ' \u00B7 ' + windowLabel + ': ' + text }, [
      dir === 'flat' ? null : el('span', { class: 'change__tri', 'aria-hidden': 'true', text: dir === 'down' ? '\u25BC' : '\u25B2' }),
      el('span', { class: 'change__value', text: text }),
      el('span', { class: 'change__window', text: windowLabel })
    ]);
  }
  function changeHtml(value, windowLabel, subject) {
    var mark = changeMark(value, windowLabel, subject);
    return mark ? mark.outerHTML : '\u2014';
  }

  /* ---------- formatadores ---------- */

  function compact(n) {
    if (n === null || n === undefined || isNaN(n)) return '--';
    var abs = Math.abs(n);
    if (abs >= 1e12) return (n / 1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(Math.round(n));
  }
  function usd(n) { return (n === null || n === undefined || isNaN(n)) ? '--' : '$' + compact(n); }
  function pct(n) { return (n === null || n === undefined || isNaN(n)) ? '--' : Number(n).toFixed(1) + '%'; }
  function day(iso) { return iso ? String(iso).slice(0, 10) : '--'; }
  function shortMint(m) { return m ? m.slice(0, 4) + '\u2026' + m.slice(-4) : '--'; }

  /* ---------- yield: observado e estimado, nunca prometido ----------
     Mesma formula de m3.fee_distribution_simulation (taxa diaria por dolar mantido):
     volume 24h indexado x taxa de transferencia empilhada / market cap.
     Qualquer entrada ausente ou <= 0 torna a estimativa indisponivel, nunca zero. */

  var YIELD_FORMULA = 'Est. 24h fee rate = indexed 24h volume \u00d7 stacked transfer fee \u00f7 market cap. Period: last 24h of indexed volume. Source: SDB index (StonkFun public API). Assumes the full stacked fee is distributed pro rata to holders; actual distribution may differ. Observed data, not a promise, guarantee or investment advice.';

  function positive(v) { var n = (v === null || v === undefined || v === '') ? NaN : Number(v); return isFinite(n) && n > 0 ? n : null; }

  function feeYield(t) {
    var volume = positive(t.volume24h), fee = positive(t.stackedTax), mc = positive(t.marketCap), missing = [];
    if (volume === null) missing.push('24h volume');
    if (fee === null) missing.push('stacked fee');
    if (mc === null) missing.push('market cap');
    if (missing.length) return { available: false, missing: missing };
    return { available: true, pct: volume * fee / mc };
  }

  function yieldPct(v) { return v >= 100 ? '>100%' : v >= 0.01 ? v.toFixed(2) + '%' : '<0.01%'; }

  function yieldText(t) {
    var y = feeYield(t);
    return y.available ? yieldPct(y.pct) : 'Unavailable';
  }
  function yieldDetail(t) {
    var y = feeYield(t);
    return y.available ? '24h vol \u00d7 ' + pct(t.stackedTax) + ' fee \u00f7 MC' : 'Missing: ' + y.missing.join(', ');
  }
  var PAYOUT_UNIT_NOTE = 'Reported in the token’s direct quote asset, which can differ from its backing asset. The token record names the unit.';
  function payoutText(t) {
    if (t.paidOut === null || t.paidOut === undefined || isNaN(t.paidOut)) return 'No payouts indexed';
    var n = Number(t.payouts);
    // payout vem na quote direta do token, nao no ativo terminal (rewardAsset); sem quoteSymbol na fonte, a unidade fica generica
    return compact(t.paidOut) + ' ' + (t.payoutUnit || 'quote units') + (isFinite(n) && t.payouts !== null && t.payouts !== undefined ? ' \u00b7 ' + compact(n) + (n === 1 ? ' payout' : ' payouts') : '');
  }

  /* Bloco "Yield" do card: pago observado + taxa estimada com formula visivel. */
  function yieldBlock(t) {
    var observed = el('b', { class: 'card__yield-value', text: payoutText(t), title: PAYOUT_UNIT_NOTE });
    var rate = el('b', { class: 'card__yield-value', text: yieldText(t) });
    var detail = el('small', { class: 'card__yield-detail', text: yieldDetail(t) });
    var box = el('div', { class: 'card__yield', title: YIELD_FORMULA }, [
      el('span', { class: 'card__yield-title', text: 'YIELD \u00b7 OBSERVED & ESTIMATED' }),
      el('div', { class: 'card__yield-line' }, [el('span', { text: 'Paid out (cumulative)' }), observed]),
      el('div', { class: 'card__yield-line' }, [el('span', { text: 'Est. 24h fee rate' }), rate]),
      detail,
      el('small', { class: 'card__yield-note', text: 'Estimate from indexed data. Not guaranteed. Not investment advice.' })
    ]);
    box._update = function (n) { setText(observed, payoutText(n)); setText(rate, yieldText(n)); setText(detail, yieldDetail(n)); };
    return box;
  }

  /* ---------- stats do drawer Display ---------- */

  var STATS = {
    mc:         { label: function () { return 'MC'; }, value: function (t) { return usd(t.marketCap); }, change: function (t) { return [t.change24h, '24h', '24h price change']; } },
    paidOut:    { label: function (t) { return 'PAID OUT (' + (t.payoutUnit || 'QUOTE UNITS') + ')'; }, value: function (t) { return compact(t.paidOut); } },
    stackedTax: { label: function () { return 'STACKED TAX'; }, value: function (t) { return pct(t.stackedTax); } },
    volume24h:  { label: function () { return 'VOLUME 24H'; }, value: function (t) { return usd(t.volume24h); } },
    fdv:        { label: function () { return 'FDV'; }, value: function (t) { return usd(t.fdv); } },
    price:      { label: function () { return 'PRICE'; }, value: function (t) { return t.price ? '$' + Number(t.price).toPrecision(4) : '--'; } },
    holders:    { label: function () { return 'HOLDERS'; }, value: function (t) { return compact(t.holders); } },
    payouts:    { label: function () { return 'PAYOUTS'; }, value: function (t) { return compact(t.payouts); } },
    change24h:  { label: function () { return 'CHANGE 24H'; }, value: function () { return ''; }, change: function (t) { return [t.change24h, '24h', '24h price change']; } },
    peakMc:     { label: function () { return 'PEAK MC'; }, value: function (t) { return usd(t.peakMarketCap); } },
    payback:    { label: function () { return 'PAYBACK'; }, value: function (t) { return t.paybackDays ? t.paybackDays + ' d' : 'no data'; } }
  };

  function statValue(def, token, node) {
    node.textContent = def.value(token);
    var ch = def.change && def.change(token);
    var mark = ch && changeMark(ch[0], ch[1], ch[2]);
    if (mark) node.appendChild(mark);
    else if (!node.textContent) node.textContent = '--';
  }

  function statCell(key, token) {
    var def = STATS[key];
    if (!def) return null;
    var label = el('span', { class: 'stat__label', text: def.label(token) });
    var value = el('span', { class: 'stat__value' });
    statValue(def, token, value);
    var cell = el('div', { class: 'stat' }, [label, value]);
    cell._update = function (t) {
      setText(label, def.label(t));
      statValue(def, t, value);
    };
    return cell;
  }

  function mintPill(mint) {
    var icon = svg('svg', { width: '11', height: '11', viewBox: '0 0 14 14', fill: 'none', 'aria-hidden': 'true' }, [
      svg('rect', { x: '4.5', y: '4.5', width: '8', height: '8', rx: '1.5', stroke: 'currentColor' }),
      svg('path', { d: 'M9.5 2.5H2.5v7', stroke: 'currentColor' })
    ]);
    var btn = el('button', { class: 'mint', type: 'button', 'aria-label': 'Copy mint address' },
      [el('span', { class: 'mint__text', text: shortMint(mint) }), icon]);
    btn.addEventListener('click', function () {
      if (!mint || !navigator.clipboard) return;
      navigator.clipboard.writeText(mint).then(function () {
        btn.classList.add('is-copied');
        setTimeout(function () { btn.classList.remove('is-copied'); }, 1200);
      });
    });
    return btn;
  }

  /* ---------- componentes ---------- */

  var registry = {};
  function component(type, factory) { registry[type] = factory; }

  component('TokenCard', function (props) {
    var stats = props.stats || ['mc', 'paidOut', 'stackedTax'];
    var meta = assetMeta(props.rewardAsset);

    var symbol = el('a', { class: 'card__symbol token-name-link', href: '#/token/' + encodeURIComponent(props.mint || ''), title: 'Open token record · indexed ' + day(props.lastPayout) }, [el('span', { text: props.symbol || '--' })]);
    var name = el('a', { class: 'card__name token-name-link', href: '#/token/' + encodeURIComponent(props.mint || ''), title: 'View token record and indexed timeline' }, [el('span', { text: props.name || '' })]);
    var statsRow = el('div', { class: 'card__stats' });
    var cells = {};
    stats.forEach(function (k) {
      var c = statCell(k, props);
      if (c) { cells[k] = c; statsRow.appendChild(c); }
    });

    var fill = el('div', { class: 'bar__fill', style: 'width:' + (props.barPct || 0) + '%' });
    var footText = el('span', { text: 'Depth ' + (props.depth || 1) + ' \u00B7 Last payout: ' + day(props.lastPayout) });
    var yieldBox = props.yield === false ? null : yieldBlock(props);

    var card = el('article', { class: 'card', style: '--asset: ' + meta.color }, [
      avatar(props.rewardAsset, 'lg', props.image),
      symbol,
      name,
      mintPill(props.mint),
      statsRow,
      yieldBox,
      el('div', { class: 'bar', title: 'Bar length: paid out relative to the largest payout on this view' }, [fill]),
      el('div', { class: 'card__foot' }, [launchpadIcon(props.launchpad), footText])
    ]);

    return {
      el: card,
      update: function (next) {
        setText(symbol, next.symbol || '--');
        setText(name, next.name || '');
        stats.forEach(function (k) { if (cells[k]) cells[k]._update(next); });
        if (yieldBox) yieldBox._update(next);
        fill.style.width = (next.barPct || 0) + '%';
        setText(footText, 'Depth ' + (next.depth || 1) + ' \u00B7 Last payout: ' + day(next.lastPayout));
      }
    };
  });

  component('TokenRow', function (props) {
    var meta = assetMeta(props.rewardAsset);
    var symbol = el('a', { class: 'row__symbol token-name-link', href: '#/token/' + encodeURIComponent(props.mint || ''), title: 'Open token record · indexed ' + day(props.lastPayout) }, [el('span', { text: props.symbol || '--' })]);
    var mc = el('span', { class: 'row__muted', text: usd(props.marketCap) });
    var paid = el('span', { class: 'row__value', text: compact(props.paidOut) });
    var tax = el('span', { class: 'row__muted', text: pct(props.stackedTax) });
    var fill = el('div', { class: 'bar__fill', style: 'width:' + (props.barPct || 0) + '%' });

    var row = el('div', { class: 'row', style: '--asset: ' + meta.color }, [
      avatar(props.rewardAsset, 'sm', props.image),
      el('div', { class: 'row__id' }, [symbol, el('span', { class: 'row__name', text: props.name || '' })]),
      launchpadIcon(props.launchpad),
      mc, paid, tax,
      el('div', { class: 'bar' }, [fill])
    ]);

    return {
      el: row,
      update: function (next) {
        setText(symbol, next.symbol || '--');
        setText(mc, usd(next.marketCap));
        setText(paid, compact(next.paidOut));
        setText(tax, pct(next.stackedTax));
        fill.style.width = (next.barPct || 0) + '%';
      }
    };
  });

  component('CreatorRow', function (props) {
    var meta = assetMeta(props.mainTokenAsset || (props.topVolumeToken && props.topVolumeToken.rewardAsset));
    var peak = el('span', { class: 'creator__peak', text: usd(props.medianPeak) });
    var launches = el('span', { class: 'creator__num', text: compact(props.launches) });
    var graduated = el('span', { class: 'creator__num', text: compact(props.graduated) });
    var top = props.topVolumeToken || {};
    var wallet = el('a', { class: 'creator__wallet', href: '#/creator/' + encodeURIComponent(props.wallet || ''), title: 'View all launches by this creator' }, [el('span', { text: props.walletShort || shortMint(props.wallet) })]);
    var topLink = top.mint ? el('a', { class: 'creator__volume-token token-name-link', href: '#/token/' + encodeURIComponent(top.mint), title: 'Open top-volume token record' }, [el('span', { text: (top.symbol || 'Top current volume') + ' · ' + usd(top.volume24hUsd) })]) : el('span', { class: 'creator__volume-token', text: 'No live volume data' });

    var row = el('div', { class: 'creator', style: '--asset: ' + meta.color }, [
      el('span', { class: 'creator__rank', text: props.rank || '' }),
      el('span', { class: 'creator__trend', 'aria-hidden': 'true' }),
      peak,
      el('div', { class: 'creator__id' }, [
        avatar(props.mainTokenAsset, 'sm'),
        el('div', {}, [
          wallet,
          topLink
        ])
      ]),
      launches,
      graduated
    ]);

    return {
      el: row,
      update: function (next) {
        setText(peak, usd(next.medianPeak));
        setText(launches, compact(next.launches));
        setText(graduated, compact(next.graduated));
      }
    };
  });

  /* /api/ticker nao traz variacao nem janela de tempo, entao o ticker nao mostra triangulo. */
  component('TickerItem', function (props) {
    var meta = assetMeta(props.asset);
    var price = el('span', { class: 'ticker__price', text: props.price != null ? Number(props.price).toFixed(2) : '--' });
    var count = el('span', { class: 'ticker__metric', text: props.tokenCount != null ? Number(props.tokenCount).toLocaleString('en-US') + ' tokens' : '' });
    var share = el('span', { class: 'ticker__metric', text: props.sharePct != null ? Number(props.sharePct).toFixed(2) + '% share' : '' });
    var item = el('span', { class: 'ticker__item', style: '--asset: ' + meta.color, title: (props.name || props.ticker || props.asset || '') + ' · ' + (props.price != null ? Number(props.price).toFixed(2) : 'price unavailable') + (props.sharePct != null ? ' · ' + Number(props.sharePct).toFixed(2) + '% of indexed tokens' : '') }, [
      avatar(props.asset, 'xs', props.logo),
      el('span', { class: 'ticker__symbol', text: props.ticker || props.asset || '--' }),
      el('span', { class: 'ticker__name', text: props.name || '' }),
      price,
      count,
      share
    ]);
    return {
      el: item,
      update: function (next) {
        setText(price, next.price != null ? Number(next.price).toFixed(2) : '--');
        setText(count, next.tokenCount != null ? Number(next.tokenCount).toLocaleString('en-US') + ' tokens' : '');
        setText(share, next.sharePct != null ? Number(next.sharePct).toFixed(2) + '% share' : '');
        item.title = (next.name || next.ticker || next.asset || '') + ' · ' + (next.price != null ? Number(next.price).toFixed(2) : 'price unavailable') + (next.sharePct != null ? ' · ' + Number(next.sharePct).toFixed(2) + '% of indexed tokens' : '');
      }
    };
  });

  /* ---------- render com reaproveitamento por key ---------- */

  var mounted = new WeakMap();

  function render(container, specs) {
    if (!container) return;
    var prev = mounted.get(container) || new Map();
    var next = new Map();
    var frag = document.createDocumentFragment();

    for (var i = 0; i < specs.length; i++) {
      var spec = specs[i];
      var key = spec.key || spec.type + ':' + i;
      var inst = prev.get(key);
      if (inst && inst.type === spec.type) {
        inst.update(spec.props);
      } else {
        var factory = registry[spec.type];
        if (!factory) continue;
        var made = factory(spec.props);
        inst = { type: spec.type, el: made.el, update: made.update };
      }
      next.set(key, inst);
      frag.appendChild(inst.el);
    }

    prev.forEach(function (inst, key) {
      if (!next.has(key) && inst.el.parentNode === container) container.removeChild(inst.el);
    });

    container.appendChild(frag);
    mounted.set(container, next);
  }

  /* ---------- adaptador da API ---------- */

  function mapToken(raw, opts) {
    opts = opts || {};
    var maxPaid = opts.maxPaidOut || 0;
    return {
      key: raw.mint,
      type: opts.type || 'TokenCard',
      props: {
        symbol: raw.symbol,
        name: raw.name,
        mint: raw.mint,
        rewardAsset: raw.rewardAsset || raw.quote || raw.backing,
        image: raw.image_url || raw.imageUrl || raw.image || null,
        marketCap: raw.marketCap,
        paidOut: raw.paidOut,
        payoutUnit: raw.payoutUnit || null,
        stackedTax: raw.stackedTax,
        volume24h: raw.volume24h,
        fdv: raw.fdv,
        price: raw.price,
        holders: raw.holders,
        payouts: raw.payouts,
        change24h: raw.change24h,
        peakMarketCap: raw.peakMarketCap,
        paybackDays: raw.paybackDays,
        depth: raw.depth,
        lastPayout: raw.lastPayout,
        launchpad: raw.launchpad,
        barPct: maxPaid ? Math.max(2, Math.round((raw.paidOut / maxPaid) * 100)) : 0,
        stats: opts.stats,
        yield: opts.yield
      }
    };
  }

  global.SDB = {
    render: render,
    component: component,
    mapToken: mapToken,
    assets: ASSETS,
    launchpads: LAUNCHPADS,
    stats: STATS,
    format: { compact: compact, usd: usd, pct: pct, day: day, shortMint: shortMint },
    feeYield: feeYield,
    yieldFormula: YIELD_FORMULA,
    changeMark: changeMark,
    changeHtml: changeHtml,
    el: el,
    avatar: avatar,
    assetMeta: assetMeta
  };
})(window);
