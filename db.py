"""SDB: storage layer (D1-7).

SQLite at data/sdb.db. The time series (`snapshots` table) is the moat: each ingestor
cycle writes a new record and never overwrites.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SDB_DATA_DIR", os.path.join(HERE, "data"))
DB_PATH = os.path.join(DATA_DIR, "sdb.db")
CORE_DB_PATH = os.path.join(DATA_DIR, "core.db")
HISTORY_DIR = os.path.join(DATA_DIR, "history")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
  mint TEXT PRIMARY KEY,
  pool TEXT, name TEXT, symbol TEXT, creator TEXT,
  launchpad TEXT, mode TEXT, quote_only_fees INTEGER,
  transfer_fee_bps INTEGER,
  quote_mint TEXT, quote_symbol TEXT, quote_name TEXT,
  quote_category TEXT, quote_category_label TEXT,
  status TEXT, graduation_progress REAL,
  graduated_at TEXT, created_at TEXT,
  price_usd REAL, market_cap_usd REAL, fdv_usd REAL,
  volume_24h_usd REAL, price_change_24h REAL, peak_market_cap_usd REAL,
  -- M1: backing chain (resolved)
  depth INTEGER, terminal_mint TEXT, terminal_symbol TEXT,
  terminal_name TEXT, terminal_category TEXT, terminal_category_label TEXT,
  chain_json TEXT, is_cycle INTEGER,
  -- token links/metadata (from the StonkFun API) + stacked tax of the chain
  image_url TEXT, stacked_tax_bps INTEGER, twitter TEXT, website TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT,
  mint TEXT,
  price_usd REAL, market_cap_usd REAL, fdv_usd REAL,
  volume_24h_usd REAL, status TEXT,
  graduation_progress REAL, peak_market_cap_usd REAL,
  transfer_fee_bps INTEGER, quote_symbol TEXT, mode TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_mint_time ON snapshots(mint, captured_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_unique ON snapshots(mint, captured_at);

CREATE TABLE IF NOT EXISTS rewards (
  mint TEXT PRIMARY KEY,
  quote_mint TEXT, quote_symbol TEXT, quote_decimals INTEGER,
  distributed_raw TEXT, distributed_tokens REAL,
  payout_count INTEGER, holder_count INTEGER, last_payout_at TEXT,
  captured_at TEXT
);

CREATE TABLE IF NOT EXISTS distributions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reward_mint TEXT, payer TEXT, holder TEXT,
  amount_raw TEXT, amount_tokens REAL,
  quote_symbol TEXT, created_at TEXT, captured_at TEXT
);

CREATE TABLE IF NOT EXISTS launches (
  mint TEXT PRIMARY KEY,
  pool TEXT, name TEXT, symbol TEXT, creator TEXT,
  quote_mint TEXT, quote_symbol TEXT,
  launchpad TEXT, mode TEXT, transfer_fee_bps INTEGER,
  start_market_cap_usd REAL, target_market_cap_usd REAL,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_launches_creator ON launches(creator);

CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT,
  token_count INTEGER,
  reward_count INTEGER,
  launch_count INTEGER
);

CREATE TABLE IF NOT EXISTS verified_creators (
  wallet TEXT PRIMARY KEY,
  handle TEXT,
  source TEXT,
  verified_at TEXT
);

-- Editorial evidence is opt-in and source-backed. Empty means no feed configured,
-- never a fabricated news stream.
CREATE TABLE IF NOT EXISTS news_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_label TEXT NOT NULL,
  source_url TEXT NOT NULL,
  title TEXT NOT NULL,
  published_at TEXT,
  retrieved_at TEXT NOT NULL,
  asset_symbol TEXT,
  project_key TEXT,
  summary TEXT,
  UNIQUE(source_url)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_evidence(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_asset ON news_evidence(asset_symbol);

-- Curated identities only. Wallet activity itself is not a KOL identity claim.
CREATE TABLE IF NOT EXISTS creator_registry (
  wallet TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  profile_url TEXT NOT NULL,
  source_label TEXT NOT NULL,
  source_url TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS asset_snapshots (
  terminal TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0,
  market_cap_usd REAL,
  volume_24h_usd REAL,
  live_count INTEGER NOT NULL DEFAULT 0,
  graduated_count INTEGER NOT NULL DEFAULT 0,
  creator_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (terminal, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_asset_snapshots_time ON asset_snapshots(terminal, captured_at);

CREATE TABLE IF NOT EXISTS terminal_prices (
  symbol TEXT PRIMARY KEY,
  ticker TEXT,
  price_usd REAL,
  captured_at TEXT
);

CREATE TABLE IF NOT EXISTS asset_feeds (
  terminal TEXT PRIMARY KEY,
  feed_id TEXT NOT NULL,
  asset_type TEXT,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS asset_prices (
  terminal TEXT NOT NULL,
  price_usd REAL NOT NULL,
  conf REAL,
  publish_time INTEGER,
  captured_at TEXT NOT NULL,
  PRIMARY KEY (terminal, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_asset_prices_terminal_time
  ON asset_prices(terminal, captured_at);

CREATE INDEX IF NOT EXISTS idx_tokens_mcap ON tokens(market_cap_usd);
CREATE INDEX IF NOT EXISTS idx_tokens_terminal ON tokens(terminal_symbol);
CREATE INDEX IF NOT EXISTS idx_tokens_creator ON tokens(creator);
CREATE INDEX IF NOT EXISTS idx_tokens_status ON tokens(status);
CREATE INDEX IF NOT EXISTS idx_tokens_created ON tokens(created_at);
CREATE INDEX IF NOT EXISTS idx_tokens_symbol ON tokens(symbol);
CREATE INDEX IF NOT EXISTS idx_rewards_last_payout ON rewards(last_payout_at);
CREATE INDEX IF NOT EXISTS idx_rewards_quote ON rewards(quote_symbol);
CREATE INDEX IF NOT EXISTS idx_launches_created ON launches(created_at);
CREATE INDEX IF NOT EXISTS idx_launches_quote ON launches(quote_symbol);

CREATE TABLE IF NOT EXISTS holders (
  mint TEXT, owner TEXT, amount_ui REAL, pct REAL, captured_at TEXT,
  PRIMARY KEY (mint, owner)
);
CREATE INDEX IF NOT EXISTS idx_holders_mint ON holders(mint);

CREATE TABLE IF NOT EXISTS token_events (
  mint TEXT, wallet TEXT, kind TEXT, signature TEXT, captured_at TEXT,
  PRIMARY KEY (mint, kind, signature)
);
CREATE INDEX IF NOT EXISTS idx_events_mint ON token_events(mint);

CREATE TABLE IF NOT EXISTS pools (
  mint TEXT PRIMARY KEY, pool TEXT, program TEXT, captured_at TEXT
);

CREATE TABLE IF NOT EXISTS burns (
  mint TEXT, signature TEXT, amount_raw REAL, decimals INTEGER, amount_ui REAL, captured_at TEXT,
  PRIMARY KEY (mint, signature)
);
CREATE INDEX IF NOT EXISTS idx_burns_mint ON burns(mint);


CREATE TABLE IF NOT EXISTS creator_scan_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  signatures_scanned INTEGER DEFAULT 0,
  transactions_checked INTEGER DEFAULT 0,
  tokens_found INTEGER DEFAULT 0,
  cursor_before TEXT,
  cursor_after TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_creator_scan_runs_creator ON creator_scan_runs(creator, started_at);

CREATE TABLE IF NOT EXISTS creator_token_evidence (
  creator TEXT NOT NULL,
  mint TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  signature TEXT NOT NULL,
  slot INTEGER,
  evidence_type TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'solana-rpc',
  PRIMARY KEY (creator, mint, signature, evidence_type)
);
CREATE INDEX IF NOT EXISTS idx_creator_token_evidence_creator ON creator_token_evidence(creator, first_seen_at);

CREATE TABLE IF NOT EXISTS api_keys (
  key_hash TEXT PRIMARY KEY,
  tier TEXT,
  quota_monthly INTEGER,
  created_at TEXT,
  last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS launchpad_sources (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
  evidence TEXT, docs_url TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS launchpad_events (
  source TEXT NOT NULL, program_id TEXT NOT NULL, signature TEXT PRIMARY KEY,
  slot INTEGER, block_time INTEGER, err_json TEXT, confirmation_status TEXT,
  captured_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_launchpad_events_source_slot ON launchpad_events(source, slot);

CREATE TABLE IF NOT EXISTS creator_watchlist (
  creator TEXT PRIMARY KEY,
  label TEXT,
  source TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  added_at TEXT NOT NULL,
  last_scanned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_creator_watchlist_priority ON creator_watchlist(enabled, priority DESC);

-- Meteora DBC additive storage: complete envelopes, configs, pools and snapshots.
CREATE TABLE IF NOT EXISTS dbc_collection_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, slot TEXT NOT NULL,
  complete INTEGER NOT NULL CHECK(complete = 1), envelope_version INTEGER NOT NULL,
  idl_version TEXT NOT NULL, sdk_version TEXT NOT NULL,
  quote_count INTEGER NOT NULL, config_count INTEGER NOT NULL, pool_count INTEGER NOT NULL,
  rpc_requests INTEGER, UNIQUE(slot, finished_at)
);
CREATE TABLE IF NOT EXISTS dbc_configs (
  address TEXT PRIMARY KEY, variant TEXT NOT NULL, quote_mint TEXT NOT NULL,
  quote_symbol TEXT, version INTEGER, collect_fee_mode INTEGER,
  migration_option INTEGER, activation_type INTEGER, token_type INTEGER,
  creator_trading_fee_percentage INTEGER,
  partner_permanent_locked_liquidity_percentage INTEGER,
  creator_permanent_locked_liquidity_percentage INTEGER,
  migration_quote_threshold TEXT, migration_base_threshold TEXT,
  migrated_pool_fee_bps INTEGER, raw_json TEXT NOT NULL,
  first_seen_run INTEGER NOT NULL REFERENCES dbc_collection_runs(id),
  last_seen_run INTEGER NOT NULL REFERENCES dbc_collection_runs(id)
);
CREATE TABLE IF NOT EXISTS dbc_pools (
  address TEXT PRIMARY KEY, variant TEXT NOT NULL,
  config_address TEXT NOT NULL REFERENCES dbc_configs(address),
  base_mint TEXT NOT NULL, creator TEXT, status TEXT NOT NULL,
  first_seen_run INTEGER NOT NULL REFERENCES dbc_collection_runs(id),
  last_seen_run INTEGER NOT NULL REFERENCES dbc_collection_runs(id)
);
CREATE TABLE IF NOT EXISTS dbc_pool_snapshots (
  run_id INTEGER NOT NULL REFERENCES dbc_collection_runs(id),
  pool_address TEXT NOT NULL REFERENCES dbc_pools(address), slot TEXT NOT NULL,
  base_reserve TEXT, quote_reserve TEXT, sqrt_price TEXT, activation_point TEXT,
  is_migrated INTEGER, migration_progress INTEGER, raw_json TEXT NOT NULL,
  PRIMARY KEY(run_id, pool_address)
);
CREATE TABLE IF NOT EXISTS dbc_checkpoints (
  name TEXT PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES dbc_collection_runs(id),
  slot TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dbc_configs_quote ON dbc_configs(quote_mint, last_seen_run);
CREATE INDEX IF NOT EXISTS idx_dbc_pools_config ON dbc_pools(config_address, last_seen_run);
CREATE INDEX IF NOT EXISTS idx_dbc_pools_base ON dbc_pools(base_mint);
CREATE INDEX IF NOT EXISTS idx_dbc_pools_status ON dbc_pools(status, last_seen_run);
CREATE INDEX IF NOT EXISTS idx_dbc_pools_variant ON dbc_pools(variant, last_seen_run);
CREATE INDEX IF NOT EXISTS idx_dbc_snapshots_pool ON dbc_pool_snapshots(pool_address, run_id DESC);
"""


def _configure_connection(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _attach_split(conn, root):
    root = os.path.abspath(root)
    core = os.path.join(root, "core.db")
    onchain = os.path.join(root, "onchain.db")
    history_files = sorted(
        os.path.join(root, "history", name)
        for name in os.listdir(os.path.join(root, "history"))
        if name.endswith(".db")
    )
    if not os.path.isfile(core) or not os.path.isfile(onchain) or not history_files:
        raise FileNotFoundError("split storage requires core.db, onchain.db, and history/*.db")
    conn.execute("ATTACH DATABASE ? AS onchain", (onchain,))
    conn.execute("ATTACH DATABASE ? AS history", (history_files[-1],))
    # Compatibility views preserve the monolithic table names for read-only staging.
    # Some older source snapshots do not contain later on-chain tables; expose an
    # empty typed view so token detail endpoints remain readable during migration.
    for table in ("snapshots", "distributions"):
        exists = conn.execute("SELECT 1 FROM history.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            conn.execute(f'CREATE TEMP VIEW "{table}" AS SELECT * FROM history."{table}"')
    fallback = {
        "holders": "mint TEXT, owner TEXT, amount_ui REAL, pct REAL, captured_at TEXT",
        "token_events": "mint TEXT, wallet TEXT, kind TEXT, signature TEXT, captured_at TEXT",
        "pools": "mint TEXT, pool TEXT, program TEXT, captured_at TEXT",
        "burns": "mint TEXT, signature TEXT, amount_raw REAL, decimals INTEGER, amount_ui REAL, captured_at TEXT",
    }
    for table, columns in fallback.items():
        exists = conn.execute("SELECT 1 FROM onchain.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            conn.execute(f'CREATE TEMP VIEW "{table}" AS SELECT * FROM onchain."{table}"')
        else:
            select_columns = ", ".join(
                f"CAST(NULL AS {decl.split()[-1]}) AS {name}"
                for name, decl in ((part.split()[0], part) for part in columns.split(", "))
            )
            conn.execute(f'CREATE TEMP VIEW "{table}" AS SELECT {select_columns} WHERE 0')
    return conn


def is_split():
    return bool(os.environ.get("SDB_SPLIT_DIR"))


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(os.environ["SDB_SPLIT_DIR"], "core.db") if is_split() else DB_PATH
    conn = sqlite3.connect(path)
    _configure_connection(conn)
    if is_split():
        _attach_split(conn, os.environ["SDB_SPLIT_DIR"])
    else:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def connect_core(path=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(path or CORE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def history_path(captured_at=None):
    stamp = captured_at or ""
    month = stamp[:7] if len(stamp) >= 7 else __import__("time").strftime("%Y-%m")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    return os.path.join(HISTORY_DIR, f"history-{month}.db")


def init_db(conn=None):
    c = conn or connect()
    # Split staging is read-only. Compatibility names are TEMP views, so the
    # monolithic schema/index script must not run against the split layout.
    if is_split():
        return
    c.executescript(SCHEMA)
    # migration: config columns added to snapshots (to track changes)
    for col, decl in (("transfer_fee_bps", "INTEGER"),
                      ("quote_symbol", "TEXT"),
                      ("mode", "TEXT")):
        has = c.execute(f"PRAGMA table_info(snapshots)").fetchall()
        if not any(r[1] == col for r in has):
            c.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {decl}")
    # migration: holder concentration (on-chain, Helius)
    has = c.execute("PRAGMA table_info(tokens)").fetchall()
    if not any(r[1] == "holder_top10_share" for r in has):
        c.execute("ALTER TABLE tokens ADD COLUMN holder_top10_share REAL")
    # migration: links/metadata + stacked tax (columns the StonkFun API provides)
    for col, decl in (("image_url", "TEXT"), ("stacked_tax_bps", "INTEGER"),
                      ("twitter", "TEXT"), ("website", "TEXT")):
        has = c.execute("PRAGMA table_info(tokens)").fetchall()
        if not any(r[1] == col for r in has):
            c.execute(f"ALTER TABLE tokens ADD COLUMN {col} {decl}")
    c.commit()
    if conn is None:
        c.close()
