'use strict';

const { PublicKey } = require('@solana/web3.js');
const bs58 = require('bs58').default;
const { createDbcProgram, DynamicBondingCurveIdl } = require('@meteora-ag/dynamic-bonding-curve-sdk');

const PROGRAM_ID = 'dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN';
const ENVELOPE_VERSION = 1;
const DEFAULTS = Object.freeze({ maxQuotes: 16, maxConfigs: 1000, maxPools: 5000, maxRpcRequests: 1200,
  deadlineMs: 600000, concurrency: 1, retries: 5, baseBackoffMs: 1000, pageSize: 100, maxPages: 20 });
const DISCRIMINATORS = Object.fromEntries(DynamicBondingCurveIdl.accounts.map(a => [a.name, Buffer.from(a.discriminator)]));

function scalar(v) {
  if (v == null || typeof v === 'boolean' || typeof v === 'string') return v;
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') return Number.isSafeInteger(v) ? v : String(v);
  if (PublicKey.isOnCurve && v instanceof PublicKey) return v.toBase58();
  if (Buffer.isBuffer(v) || v instanceof Uint8Array) return Buffer.from(v).toString('base64');
  if (v && typeof v.toBase58 === 'function') return v.toBase58();
  if (v && typeof v.toString === 'function' && (v.constructor?.name === 'BN')) return v.toString(10);
  if (Array.isArray(v)) return v.map(scalar);
  if (typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, scalar(x)]));
  throw new Error('unsupported decoded value');
}
function pick(o, ...names) { for (const n of names) if (o && o[n] !== undefined) return o[n]; return null; }
function normalizeConfig(pubkey, variant, account, quoteHint) {
  const c = account.config || account;
  return { address: pubkey, variant, quoteMint: String(pick(c, 'quoteMint', 'quote_mint') || quoteHint),
    version: scalar(pick(c, 'version')), collectFeeMode: scalar(pick(c, 'collectFeeMode', 'collect_fee_mode')),
    migrationOption: scalar(pick(c, 'migrationOption', 'migration_option')),
    activationType: scalar(pick(c, 'activationType', 'activation_type')),
    tokenType: scalar(pick(c, 'tokenType', 'token_type')),
    creatorTradingFeePercentage: scalar(pick(c, 'creatorTradingFeePercentage', 'creator_trading_fee_percentage')),
    partnerPermanentLockedLiquidityPercentage: scalar(pick(c, 'partnerPermanentLockedLiquidityPercentage', 'partner_permanent_locked_liquidity_percentage')),
    creatorPermanentLockedLiquidityPercentage: scalar(pick(c, 'creatorPermanentLockedLiquidityPercentage', 'creator_permanent_locked_liquidity_percentage')),
    migrationQuoteThreshold: scalar(pick(c, 'migrationQuoteThreshold', 'migration_quote_threshold')),
    migrationBaseThreshold: scalar(pick(c, 'migrationBaseThreshold', 'migration_base_threshold')),
    migratedPoolFeeBps: scalar(pick(c, 'migratedPoolFeeBps', 'migrated_pool_fee_bps')),
    raw: scalar(c) };
}
function normalizePool(pubkey, variant, account, configHint, slot) {
  const p = account.poolState || account.pool_state || account;
  return { address: pubkey, variant, config: String(pick(p, 'config') || configHint),
    baseMint: scalar(pick(p, 'baseMint', 'base_mint')), creator: scalar(pick(p, 'creator')),
    baseReserve: scalar(pick(p, 'baseReserve', 'base_reserve')), quoteReserve: scalar(pick(p, 'quoteReserve', 'quote_reserve')),
    sqrtPrice: scalar(pick(p, 'sqrtPrice', 'sqrt_price')), activationPoint: scalar(pick(p, 'activationPoint', 'activation_point')),
    isMigrated: scalar(pick(p, 'isMigrated', 'is_migrated')), migrationProgress: scalar(pick(p, 'migrationProgress', 'migration_progress')),
    slot: String(slot), raw: scalar(p) };
}
function validateQuotes(doc) {
  if (!doc || doc.version !== 1 || !Array.isArray(doc.quotes)) throw new Error('quote file must contain version 1 and quotes[]');
  const seen = new Set();
  return doc.quotes.map(q => { const mint = new PublicKey(q.mint).toBase58(); if (seen.has(mint)) throw new Error('duplicate quote mint'); seen.add(mint); return { mint, symbol: String(q.symbol || '').slice(0, 24) }; });
}
function parseLimits(env = process.env) {
  const out = {};
  for (const [k, d] of Object.entries(DEFAULTS)) { const key = 'DBC_' + k.replace(/[A-Z]/g, x => '_' + x).toUpperCase(); const n = Number(env[key] ?? d); if (!Number.isInteger(n) || n < 1 || n > d) throw new Error(`${key} must be integer 1..${d}`); out[k] = n; }
  return out;
}
class Rpc {
  constructor(url, limits) { this.url = url; this.limits = limits; this.started = Date.now(); this.requests = 0; this.id = 0; }
  async call(method, params) {
    if (++this.requests > this.limits.maxRpcRequests) throw new Error('RPC request limit exceeded');
    let last;
    for (let attempt = 0; attempt <= this.limits.retries; attempt++) {
      const left = this.limits.deadlineMs - (Date.now() - this.started); if (left <= 0) throw new Error('collector deadline exceeded');
      const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), Math.min(left, 30000));
      try { const r = await fetch(this.url, { method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({jsonrpc:'2.0',id:++this.id,method,params}), signal:ctl.signal });
        if (!r.ok) throw new Error(`RPC HTTP ${r.status}`); const j = await r.json(); if (j.error) throw new Error(`RPC ${j.error.code}: ${j.error.message}`); return j.result;
      } catch (e) { last=e; if (attempt < this.limits.retries) await new Promise(r => setTimeout(r, this.limits.baseBackoffMs * (2 ** attempt))); }
      finally { clearTimeout(timer); }
    } throw last;
  }
}
async function mapLimited(items, concurrency, fn) { const out = new Array(items.length); let next=0; async function worker(){ while(next<items.length){ const i=next++; out[i]=await fn(items[i],i); } } await Promise.all(Array.from({length:Math.min(concurrency,items.length)},worker)); return out; }
function gpaFilters(discriminator, offset, key) { return [{ memcmp:{ offset:0, bytes:bs58.encode(discriminator) } }, { memcmp:{ offset, bytes:key } }]; }
function normalizePage(result) {
  const page = result?.value && !Array.isArray(result.value) ? result.value : result;
  const rows = page?.accounts || page?.value || page || [];
  if (!Array.isArray(rows)) throw new Error(`invalid paginated account response: ${JSON.stringify(Object.keys(page || {}))}`);
  return {rows, paginationKey: page?.paginationKey || page?.pagination_key || result?.paginationKey || result?.pagination_key || null};
}
async function collect({rpcUrl, quotes, limits=parseLimits(), now=()=>new Date().toISOString(), rpcMethod=process.env.DBC_RPC_METHOD || 'getProgramAccounts'}) {
  if (!rpcUrl || !/^https?:\/\//.test(rpcUrl)) throw new Error('DBC_RPC_URL must be an http(s) URL');
  if (quotes.length > limits.maxQuotes) throw new Error('quote limit exceeded');
  const rpc = new Rpc(rpcUrl, limits); const fakeConnection = { commitment:'confirmed' }; const {program}=createDbcProgram(fakeConnection);
  const dec=(name,b64)=>program.coder.accounts.decode(name[0].toLowerCase()+name.slice(1),Buffer.from(b64,'base64'));
  if (!['getProgramAccounts', 'getProgramAccountsV2'].includes(rpcMethod)) throw new Error('unsupported DBC_RPC_METHOD');
  async function getAccounts(name, offset, key) {
    const filters = gpaFilters(DISCRIMINATORS[name], offset, key);
    const all = [];
    let paginationKey;
    for (let page = 0; page < limits.maxPages; page++) {
      const options = {encoding:'base64', commitment:'confirmed', withContext:true, filters};
      if (rpcMethod === 'getProgramAccountsV2') {
        options.limit = limits.pageSize;
        if (paginationKey) options.paginationKey = paginationKey;
      }
      const result = await rpc.call(rpcMethod, [PROGRAM_ID, options]);
      const page = normalizePage(result);
      const rows = page.rows;
      all.push(...rows);
      const next = page.paginationKey;
      if (rpcMethod !== 'getProgramAccountsV2' || !next || rows.length === 0) break;
      if (next === paginationKey) throw new Error('pagination cursor did not advance');
      paginationKey = next;
    }
    return all;
  }
  const startedAt=now(); const slotResult=await rpc.call('getSlot',[{commitment:'confirmed'}]); const slot=String(slotResult);
  const configs=[]; const configSeen=new Set();
  for (const q of quotes) for (const variant of ['PoolConfig','ConfigWithTransferHook']) {
    const result=await getAccounts(variant,8,q.mint); const rows=result.value || result;
    for(const r of rows){ if(configSeen.has(r.pubkey)) continue; if(configs.length>=limits.maxConfigs) throw new Error('config limit exceeded'); configSeen.add(r.pubkey); configs.push(normalizeConfig(r.pubkey,variant,dec(variant,r.account.data[0]),q.mint)); }
  }
  let poolCount=0;
  const poolGroups=await mapLimited(configs,limits.concurrency,async c=>{ const rows=[]; for(const variant of ['VirtualPool','TransferHookPool']) { const result=await getAccounts(variant,72,c.address); for(const r of result) { if(++poolCount>limits.maxPools) throw new Error('pool limit exceeded'); rows.push(normalizePool(r.pubkey,variant,dec(variant,r.account.data[0]),c.address,slot)); } } return rows; });
  const poolSeen=new Set(); const pools=[]; for(const row of poolGroups.flat()){ if(poolSeen.has(row.address)) throw new Error('duplicate pool address'); poolSeen.add(row.address); pools.push(row); }
  const finishedAt=now(); return {version:ENVELOPE_VERSION,complete:true,programId:PROGRAM_ID,idlVersion:'0.2.1',sdkVersion:'1.5.12',startedAt,finishedAt,slot,
    limits,rpcMethod,stats:{quotes:quotes.length,configs:configs.length,pools:pools.length,rpcRequests:rpc.requests},quotes,configs,pools};
}
module.exports={PROGRAM_ID,DISCRIMINATORS,scalar,normalizeConfig,normalizePool,validateQuotes,parseLimits,gpaFilters,normalizePage,collect};

if(require.main===module){ (async()=>{ const fs=require('fs'); const path=require('path'); const qpath=process.env.DBC_QUOTES_FILE || path.resolve(__dirname,'../../config/dbc_quote_mints.json'); const quotes=validateQuotes(JSON.parse(fs.readFileSync(qpath,'utf8'))); const data=await collect({rpcUrl:process.env.DBC_RPC_URL,quotes:quotes.slice(0,parseLimits().maxQuotes)}); process.stdout.write(JSON.stringify(data)+'\n'); })().catch(e=>{ process.stderr.write(`meteora-dbc: ${e.message}\n`); process.exit(1); }); }
