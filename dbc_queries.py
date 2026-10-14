"""Bounded SQL-only read model for Meteora DBC HTTP APIs."""
import re
from decimal import Decimal, InvalidOperation
B58=re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SORTS={"newest":"p.first_seen_run DESC,p.address","base_reserve":"length(s.base_reserve) DESC,s.base_reserve DESC,p.address","quote_reserve":"length(s.quote_reserve) DESC,s.quote_reserve DESC,p.address","progress":"s.migration_progress DESC,p.address"}
class QueryError(ValueError): pass

def _progress(reserve, threshold):
    try:
        if threshold is None or Decimal(threshold) <= 0: return None
        value=Decimal(reserve or "0")/Decimal(threshold)
        return format(min(Decimal(1),max(Decimal(0),value)).quantize(Decimal("0.0001")),"f")
    except (InvalidOperation, ValueError): return None

def _one(qs,key,default=""):
    v=qs.get(key,[default]); return v[0] if isinstance(v,list) else v

def summary(conn):
    run=conn.execute("SELECT * FROM dbc_collection_runs WHERE complete=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not run: return {"available":False,"freshness":None,"stats":{"configs":0,"pools":0}}
    quotes=conn.execute("SELECT quote_symbol symbol,quote_mint mint,COUNT(*) configs FROM dbc_configs WHERE last_seen_run=? GROUP BY quote_mint,quote_symbol ORDER BY quote_symbol",(run["id"],)).fetchall()
    statuses=conn.execute("SELECT status,COUNT(*) count FROM dbc_pools WHERE last_seen_run=? GROUP BY status",(run["id"],)).fetchall()
    return {"available":True,"freshness":{"capturedAt":run["finished_at"],"slot":run["slot"],"runId":run["id"]},"stats":{"quotes":run["quote_count"],"configs":run["config_count"],"pools":run["pool_count"],"rpcRequests":run["rpc_requests"],"byStatus":{r["status"]:r["count"] for r in statuses}},"quotes":[dict(r) for r in quotes]}

def pools(conn,qs):
    try: limit=int(_one(qs,"limit","50")); offset=int(_one(qs,"offset","0"))
    except ValueError as exc: raise QueryError("limit and offset must be integers") from exc
    if not 1<=limit<=100 or not 0<=offset<=10000: raise QueryError("pagination out of bounds")
    quote=_one(qs,"quote"); status=_one(qs,"status"); variant=_one(qs,"variant"); sort=_one(qs,"sort","newest")
    if quote and not B58.fullmatch(quote): raise QueryError("invalid quote mint")
    if status and status not in {"active","migrated"}: raise QueryError("invalid status")
    if variant and variant not in {"VirtualPool","TransferHookPool"}: raise QueryError("invalid variant")
    if sort not in SORTS: raise QueryError("invalid sort")
    where=["p.last_seen_run=cp.run_id"]; args=[]
    for value,sql in ((quote,"c.quote_mint=?"),(status,"p.status=?"),(variant,"p.variant=?")):
        if value: where.append(sql); args.append(value)
    base=" FROM dbc_pools p JOIN dbc_configs c ON c.address=p.config_address JOIN dbc_checkpoints cp ON cp.name='latest' JOIN dbc_pool_snapshots s ON s.run_id=cp.run_id AND s.pool_address=p.address"
    clause=" WHERE "+" AND ".join(where)
    total=conn.execute("SELECT COUNT(*)"+base+clause,args).fetchone()[0]
    rows=conn.execute("SELECT p.address,p.variant,p.config_address configAddress,p.base_mint baseMint,p.creator,p.status,c.quote_mint quoteMint,c.quote_symbol quoteSymbol,c.token_type tokenType,c.creator_trading_fee_percentage creatorTradingFeePercentage,c.partner_permanent_locked_liquidity_percentage partnerPermanentLockedLiquidityPercentage,c.creator_permanent_locked_liquidity_percentage creatorPermanentLockedLiquidityPercentage,c.migration_quote_threshold migrationQuoteThreshold,c.migration_base_threshold migrationBaseThreshold,c.migrated_pool_fee_bps migratedPoolFeeBps,s.slot,s.base_reserve baseReserve,s.quote_reserve quoteReserve,s.sqrt_price sqrtPrice,s.activation_point activationPoint,s.is_migrated isMigrated,s.migration_progress migrationProgress,t.symbol tokenSymbol,t.name tokenName,t.image_url tokenImageUrl,t.market_cap_usd tokenMarketCapUsd"+base+" LEFT JOIN tokens t ON t.mint=p.base_mint"+clause+" ORDER BY "+SORTS[sort]+" LIMIT ? OFFSET ?",args+[limit,offset]).fetchall()
    out=[]
    for row in rows:
        item=dict(row); item["curveProgress"]=_progress(item["quoteReserve"],item["migrationQuoteThreshold"]); out.append(item)
    cp=conn.execute("SELECT slot,updated_at FROM dbc_checkpoints WHERE name='latest'").fetchone()
    return {"total":total,"limit":limit,"offset":offset,"asOfSlot":cp["slot"] if cp else None,"asOf":cp["updated_at"] if cp else None,"pools":out}

def liquidity_summary(conn):
    data = pools(conn, {"limit": ["100"], "offset": ["0"], "sort": ["newest"]})
    return {"status": "indexed" if data["pools"] else "unavailable", "totalPools": data["total"], "tvlUsd": None, "tvlStatus": "not_configured", "tvlReason": "verified_quote_price_not_configured", "asOf": data.get("asOf"), "asOfSlot": data.get("asOfSlot"), "source": "persisted_meteora_dbc_snapshots"}

def overview(conn):
    run=conn.execute("SELECT * FROM dbc_collection_runs WHERE complete=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not run: return {"status":"unavailable","reason":"no_complete_collection"}
    statuses=conn.execute("SELECT status,COUNT(*) count FROM dbc_pools WHERE last_seen_run=? GROUP BY status",(run["id"],)).fetchall()
    variants=conn.execute("SELECT variant,COUNT(*) count FROM dbc_pools WHERE last_seen_run=? GROUP BY variant",(run["id"],)).fetchall()
    quotes=conn.execute("SELECT c.quote_symbol symbol,c.quote_mint mint,COUNT(*) pools FROM dbc_pools p JOIN dbc_configs c ON c.address=p.config_address WHERE p.last_seen_run=? GROUP BY c.quote_mint,c.quote_symbol ORDER BY pools DESC",(run["id"],)).fetchall()
    progress=conn.execute("SELECT migration_progress,COUNT(*) count FROM dbc_pool_snapshots WHERE run_id=? GROUP BY migration_progress ORDER BY migration_progress",(run["id"],)).fetchall()
    return {"status":"indexed","capture":{"runId":run["id"],"capturedAt":run["finished_at"],"slot":run["slot"],"rpcRequests":run["rpc_requests"]},"counts":{"quotes":run["quote_count"],"configs":run["config_count"],"pools":run["pool_count"]},"byStatus":{r["status"]:r["count"] for r in statuses},"byVariant":{r["variant"]:r["count"] for r in variants},"byMigrationProgress":{str(r["migration_progress"]):r["count"] for r in progress},"quotes":[dict(r) for r in quotes],"tvl":{"status":"not_configured","reason":"verified_quote_price_not_configured"},"source":"persisted_meteora_dbc_snapshots"}

def pool_history(conn,address,limit=100):
    if not B58.fullmatch(address): raise QueryError("invalid pool address")
    if not 1 <= limit <= 500: raise QueryError("limit out of bounds")
    rows=conn.execute("SELECT s.run_id,s.pool_address,s.slot,s.base_reserve baseReserve,s.quote_reserve quoteReserve,s.sqrt_price sqrtPrice,s.activation_point activationPoint,s.is_migrated isMigrated,s.migration_progress migrationProgress,r.finished_at capturedAt FROM dbc_pool_snapshots s JOIN dbc_collection_runs r ON r.id=s.run_id WHERE s.pool_address=? ORDER BY s.run_id ASC LIMIT ?",(address,limit)).fetchall()
    return {"address":address,"count":len(rows),"status":"indexed" if rows else "unavailable","points":[dict(r) for r in rows],"source":"persisted_meteora_dbc_snapshots"}

def token_pools(conn, mint, limit=20):
    """Return only DBC pools whose persisted base_mint equals the token mint."""
    if not isinstance(mint, str) or not B58.fullmatch(mint):
        raise QueryError("invalid token mint")
    if not 1 <= limit <= 100:
        raise QueryError("limit out of bounds")
    base = """ FROM dbc_pools p
        JOIN dbc_configs c ON c.address=p.config_address
        JOIN dbc_checkpoints cp ON cp.name='latest'
        JOIN dbc_pool_snapshots s ON s.run_id=cp.run_id AND s.pool_address=p.address
        LEFT JOIN tokens t ON t.mint=p.base_mint
        WHERE p.base_mint=? AND p.last_seen_run=cp.run_id"""
    rows = conn.execute("""SELECT p.address,p.variant,p.config_address configAddress,
        p.base_mint baseMint,p.creator,p.status,c.quote_mint quoteMint,c.quote_symbol quoteSymbol,
        c.token_type tokenType,c.migration_quote_threshold migrationQuoteThreshold,
        c.migration_base_threshold migrationBaseThreshold,s.slot,s.base_reserve baseReserve,
        s.quote_reserve quoteReserve,s.sqrt_price sqrtPrice,s.activation_point activationPoint,
        s.is_migrated isMigrated,s.migration_progress migrationProgress,r.finished_at capturedAt,
        t.symbol tokenSymbol,t.name tokenName,t.image_url tokenImageUrl,t.market_cap_usd tokenMarketCapUsd
        FROM dbc_pools p JOIN dbc_configs c ON c.address=p.config_address
        JOIN dbc_checkpoints cp ON cp.name='latest'
        JOIN dbc_pool_snapshots s ON s.run_id=cp.run_id AND s.pool_address=p.address
        JOIN dbc_collection_runs r ON r.id=cp.run_id
        LEFT JOIN tokens t ON t.mint=p.base_mint
        WHERE p.base_mint=? AND p.last_seen_run=cp.run_id
        ORDER BY p.address LIMIT ?""", (mint, limit)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        item["curveProgress"]=_progress(item["quoteReserve"], item["migrationQuoteThreshold"])
        out.append(item)
    return {"mint": mint, "available": bool(out), "count": len(out), "pools": out}


def pool_detail(conn,address):
    if not B58.fullmatch(address): raise QueryError("invalid pool address")
    row=conn.execute("SELECT p.address,p.variant,p.config_address configAddress,p.base_mint baseMint,p.creator,p.status,c.quote_mint quoteMint,c.quote_symbol quoteSymbol,c.token_type tokenType,c.creator_trading_fee_percentage creatorTradingFeePercentage,c.partner_permanent_locked_liquidity_percentage partnerPermanentLockedLiquidityPercentage,c.creator_permanent_locked_liquidity_percentage creatorPermanentLockedLiquidityPercentage,c.migration_quote_threshold migrationQuoteThreshold,c.migration_base_threshold migrationBaseThreshold,c.migrated_pool_fee_bps migratedPoolFeeBps,s.slot,s.base_reserve baseReserve,s.quote_reserve quoteReserve,s.sqrt_price sqrtPrice,s.activation_point activationPoint,s.is_migrated isMigrated,s.migration_progress migrationProgress,r.finished_at capturedAt,t.symbol tokenSymbol,t.name tokenName,t.image_url tokenImageUrl,t.market_cap_usd tokenMarketCapUsd FROM dbc_pools p JOIN dbc_configs c ON c.address=p.config_address JOIN dbc_checkpoints cp ON cp.name='latest' JOIN dbc_pool_snapshots s ON s.run_id=cp.run_id AND s.pool_address=p.address JOIN dbc_collection_runs r ON r.id=cp.run_id LEFT JOIN tokens t ON t.mint=p.base_mint WHERE p.address=?",(address,)).fetchone()
    if not row:return None
    history=conn.execute("SELECT s.slot,s.base_reserve baseReserve,s.quote_reserve quoteReserve,s.sqrt_price sqrtPrice,s.migration_progress migrationProgress,r.finished_at capturedAt FROM dbc_pool_snapshots s JOIN dbc_collection_runs r ON r.id=s.run_id WHERE s.pool_address=? ORDER BY s.run_id DESC LIMIT 100",(address,)).fetchall()
    pool=dict(row); pool["curveProgress"]=_progress(pool["quoteReserve"],pool["migrationQuoteThreshold"])
    return {"pool":pool,"snapshots":[dict(r) for r in history]}
