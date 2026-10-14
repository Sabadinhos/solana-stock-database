# RPC strategy

Target: Helius free plan. 1M credits/month, 10 req/s.

| Method | Credits | When |
| --- | ---: | --- |
| getTokenLargestAccounts | 1 | per token, per onchain run |
| getTokenSupply | 1 | per token, cached 5 min |
| getSignaturesForAddress | 1 | per token, new signatures only |
| getTransaction | 1 | per new successful signature |
| getAccountInfo | 1 | per pool, once a day |
| getProgramAccountsV2 | 1/page | DBC, every 6 cycles |
| getAsset | 10 | token images, cached 24 h |

Onchain runs every 6 cycles (90 min) on the top 100 tokens.

## Rules

- Cursor per mint. Each transaction is read once.
- Failed transactions are skipped.
- 429 honors `Retry-After`. 5 failures pause calls for 60 s.

## Usage

`GET /api/rpc-stats` or MCP `get_rpc_stats`.

Benchmark: 71% fewer credits at low activity, 29% at high. See [RESULTS](../bench/RESULTS.md).
