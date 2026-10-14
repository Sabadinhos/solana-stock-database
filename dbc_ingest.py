"""Strict, atomic ingestion of complete Meteora DBC collector envelopes."""
import json
import re
from datetime import datetime

PROGRAM_ID = "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN"
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEC = re.compile(r"^(0|[1-9][0-9]*)$")
CONFIG_VARIANTS = {"PoolConfig", "ConfigWithTransferHook"}
POOL_VARIANTS = {"VirtualPool", "TransferHookPool"}
MAX_CONFIGS, MAX_POOLS = 1000, 5000

class ValidationError(ValueError): pass

def _obj(v, name):
    if not isinstance(v, dict): raise ValidationError(f"{name} must be an object")
    return v
def _list(v, name, maximum):
    if not isinstance(v, list) or len(v) > maximum: raise ValidationError(f"{name} invalid or too large")
    return v
def _b58(v, name):
    if not isinstance(v, str) or not B58.fullmatch(v): raise ValidationError(f"invalid {name}")
    return v
def _dec(v, name, bits):
    if v is None: return None
    if not isinstance(v, str) or not DEC.fullmatch(v) or int(v) >= 1 << bits: raise ValidationError(f"invalid {name}")
    return v
def _iso(v, name):
    if not isinstance(v, str): raise ValidationError(f"invalid {name}")
    try: datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc: raise ValidationError(f"invalid {name}") from exc
    return v
def _small_int(v, name):
    if v is None: return None
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 65535: raise ValidationError(f"invalid {name}")
    return v

def validate(payload):
    p = _obj(payload, "envelope")
    required = {"version","complete","programId","idlVersion","sdkVersion","startedAt","finishedAt","slot","stats","quotes","configs","pools"}
    if not required.issubset(p): raise ValidationError("missing envelope fields")
    if p["version"] != 1 or p["complete"] is not True or p["programId"] != PROGRAM_ID: raise ValidationError("unsupported or incomplete envelope")
    if p["idlVersion"] != "0.2.1" or p["sdkVersion"] != "1.5.12": raise ValidationError("unexpected SDK or IDL version")
    _iso(p["startedAt"], "startedAt"); _iso(p["finishedAt"], "finishedAt"); slot=_dec(p["slot"], "slot", 64)
    configs=_list(p["configs"], "configs", MAX_CONFIGS); pools=_list(p["pools"], "pools", MAX_POOLS); quotes=_list(p["quotes"], "quotes", 16)
    quote_map={_b58(q.get("mint"),"quote mint"):str(q.get("symbol", ""))[:24] for q in map(lambda x:_obj(x,"quote"),quotes)}
    seen_c=set(); norm_c=[]
    for c in configs:
        c=_obj(c,"config"); addr=_b58(c.get("address"),"config address"); variant=c.get("variant"); quote=_b58(c.get("quoteMint"),"config quote mint")
        if addr in seen_c or variant not in CONFIG_VARIANTS or quote not in quote_map: raise ValidationError("invalid or duplicate config")
        seen_c.add(addr); norm_c.append((addr,variant,quote,quote_map[quote],_small_int(c.get("version"),"config version"),_small_int(c.get("collectFeeMode"),"collectFeeMode"),_small_int(c.get("migrationOption"),"migrationOption"),_small_int(c.get("activationType"),"activationType"),_small_int(c.get("tokenType"),"tokenType"),_small_int(c.get("creatorTradingFeePercentage"),"creatorTradingFeePercentage"),_small_int(c.get("partnerPermanentLockedLiquidityPercentage"),"partnerPermanentLockedLiquidityPercentage"),_small_int(c.get("creatorPermanentLockedLiquidityPercentage"),"creatorPermanentLockedLiquidityPercentage"),_dec(c.get("migrationQuoteThreshold"),"migrationQuoteThreshold",64),_dec(c.get("migrationBaseThreshold"),"migrationBaseThreshold",64),_small_int(c.get("migratedPoolFeeBps"),"migratedPoolFeeBps"),json.dumps(c.get("raw"),separators=(",",":"),sort_keys=True)))
    seen_p=set(); norm_p=[]
    for x in pools:
        x=_obj(x,"pool"); addr=_b58(x.get("address"),"pool address"); variant=x.get("variant"); config=_b58(x.get("config"),"pool config"); base=_b58(x.get("baseMint"),"base mint"); creator=_b58(x.get("creator"),"creator") if x.get("creator") else None
        if addr in seen_p or variant not in POOL_VARIANTS or config not in seen_c: raise ValidationError("invalid or duplicate pool")
        if x.get("slot") != slot: raise ValidationError("pool slot mismatch")
        seen_p.add(addr); norm_p.append((addr,variant,config,base,creator,_dec(x.get("baseReserve"),"baseReserve",64),_dec(x.get("quoteReserve"),"quoteReserve",64),_dec(x.get("sqrtPrice"),"sqrtPrice",128),_dec(x.get("activationPoint"),"activationPoint",64),_small_int(x.get("isMigrated"),"isMigrated"),_small_int(x.get("migrationProgress"),"migrationProgress"),json.dumps(x.get("raw"),separators=(",",":"),sort_keys=True)))
    stats=_obj(p["stats"],"stats")
    if stats.get("configs") != len(configs) or stats.get("pools") != len(pools) or stats.get("quotes") != len(quotes): raise ValidationError("stats do not match payload")
    return p, slot, norm_c, norm_p

def ingest(conn, payload):
    p,slot,configs,pools=validate(payload)
    try:
        conn.execute("BEGIN IMMEDIATE")
        dup=conn.execute("SELECT id FROM dbc_collection_runs WHERE slot=? AND finished_at=? AND complete=1",(slot,p["finishedAt"])).fetchone()
        if dup: conn.rollback(); return dup[0]
        cur=conn.execute("INSERT INTO dbc_collection_runs(started_at,finished_at,slot,complete,envelope_version,idl_version,sdk_version,quote_count,config_count,pool_count,rpc_requests) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(p["startedAt"],p["finishedAt"],slot,1,1,p["idlVersion"],p["sdkVersion"],len(p["quotes"]),len(configs),len(pools),p["stats"].get("rpcRequests")))
        run_id=cur.lastrowid
        for c in configs:
            conn.execute("INSERT INTO dbc_configs(address,variant,quote_mint,quote_symbol,version,collect_fee_mode,migration_option,activation_type,token_type,creator_trading_fee_percentage,partner_permanent_locked_liquidity_percentage,creator_permanent_locked_liquidity_percentage,migration_quote_threshold,migration_base_threshold,migrated_pool_fee_bps,raw_json,first_seen_run,last_seen_run) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET variant=excluded.variant,quote_mint=excluded.quote_mint,quote_symbol=excluded.quote_symbol,version=excluded.version,collect_fee_mode=excluded.collect_fee_mode,migration_option=excluded.migration_option,activation_type=excluded.activation_type,token_type=excluded.token_type,creator_trading_fee_percentage=excluded.creator_trading_fee_percentage,partner_permanent_locked_liquidity_percentage=excluded.partner_permanent_locked_liquidity_percentage,creator_permanent_locked_liquidity_percentage=excluded.creator_permanent_locked_liquidity_percentage,migration_quote_threshold=excluded.migration_quote_threshold,migration_base_threshold=excluded.migration_base_threshold,migrated_pool_fee_bps=excluded.migrated_pool_fee_bps,raw_json=excluded.raw_json,last_seen_run=excluded.last_seen_run",c+(run_id,run_id))
        for x in pools:
            status="migrated" if x[9] else "active"
            conn.execute("INSERT INTO dbc_pools(address,variant,config_address,base_mint,creator,status,first_seen_run,last_seen_run) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET variant=excluded.variant,config_address=excluded.config_address,base_mint=excluded.base_mint,creator=excluded.creator,status=excluded.status,last_seen_run=excluded.last_seen_run",x[:5]+(status,run_id,run_id))
            conn.execute("INSERT INTO dbc_pool_snapshots(run_id,pool_address,slot,base_reserve,quote_reserve,sqrt_price,activation_point,is_migrated,migration_progress,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(run_id,x[0],slot)+x[5:])
        conn.execute("INSERT INTO dbc_checkpoints(name,run_id,slot,updated_at) VALUES('latest',?,?,?) ON CONFLICT(name) DO UPDATE SET run_id=excluded.run_id,slot=excluded.slot,updated_at=excluded.updated_at",(run_id,slot,p["finishedAt"]))
        conn.commit(); return run_id
    except Exception:
        conn.rollback(); raise
