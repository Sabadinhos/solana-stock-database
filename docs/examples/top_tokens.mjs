// Print SDB tokens above a market cap floor. Node 18+.
// Usage: node top_tokens.mjs [min_market_cap_usd] [base_url]
const floor = Number(process.argv[2] ?? 1_000_000);
const base = process.argv[3] ?? 'https://solanastockdatabase.com';

const { cards } = await (await fetch(`${base}/api/cards?limit=500`)).json();
const top = cards
  .filter((c) => (c.market_cap_usd ?? 0) >= floor)
  .sort((a, b) => b.market_cap_usd - a.market_cap_usd);

for (const c of top) console.log(c.symbol.padEnd(10), (c.terminal ?? '-').padEnd(6), `$${Math.round(c.market_cap_usd).toLocaleString('en-US')}`, c.mint);
console.log(`${top.length} tokens >= $${floor.toLocaleString('en-US')}`);
