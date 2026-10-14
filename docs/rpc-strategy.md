# RPC strategy

SDB targets the Helius free plan: 1M credits per month and 10 requests per second. Prices below are from helius.dev/docs/billing/credits.

## Where credits go

| Method | Credits | Used by | Frequency |
| --- | ---: | --- | --- |
| getTokenLargestAccounts | 1 | onchain.py | once per token per onchain run |
| getTokenSupply | 1 | onchain.py | once per token per run, cached in-process for 5 min |
| getSignaturesForAddress | 1 | onchain.py | once per token per run, more pages only when many new signatures exist |
| getTransaction | 1 | onchain.py | once per new successful signature |
| getAccountInfo | 1 | onchain.py | once per pool per 24 h |
| getProgramAccountsV2 | 1 per page | Meteora DBC collector | every 6 scheduler cycles |
| getProgramAccounts | 10 | Meteora DBC collector | only when `DBC_RPC_METHOD=getProgramAccounts` |
| getAsset (DAS) | 10 | token image lookup in server.py | on demand, cached 24 h |

The onchain step runs every 6 scheduler cycles (90 minutes by default) on the top `SDB_ONCHAIN_TOP_N` tokens (default 100).

## Decisions

- Incremental signatures. A cursor per mint in `rpc_cursors` is passed as `until`, so each transaction is fetched once. When a run sees a full page, it pages back with `before` until the cursor, so no signature between runs is skipped.
- Skip failed transactions. A failed transaction cannot mint, burn or change authority.
- getProgramAccountsV2 by default for DBC. Same data, paginated, 1 credit per page instead of 10. The collector fails instead of truncating if the page limit is reached.
- No JSON-RPC batching. Batching reduces HTTP round trips, not credits. On the free plan credits are the constraint, so it was left out to keep the client simple.
- Not adopted: Enhanced Transactions (100 credits per request, maintenance mode). DAS getTokenAccounts for full holder lists (10 credits per page, raises cost; top 20 holders is enough for the concentration metric).
- Retries. 429 honors `Retry-After`, other retries use exponential backoff with jitter. After 5 consecutive failed calls the client stops calling for 60 s.

## Accounting

`helius.py` counts calls, credits, 429s, errors and cache hits per method. Each collector process merges its counters into `data/rpc-stats.json` on exit (aggregates only, no URL or key). The scheduler heartbeat carries today's totals. Read them with `GET /api/rpc-stats` or the MCP tool `get_rpc_stats`.

## Legacy mode

`SDB_ONCHAIN_LEGACY=1` restores the previous behavior: re-read the latest 20 signatures every run, fetch every transaction, refresh pools every run. It exists for benchmarking.
