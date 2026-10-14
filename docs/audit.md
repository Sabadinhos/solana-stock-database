# RPC and repository audit

Scope: commit `afcfe34` on `main`. Static reading of the root modules plus `ingestor/`, `collectors/`, `config/`, `web/` and `tests/`. Credit costs are taken from the Helius credits page (helius.dev/docs/billing/credits), read on 2026-10-14. No production numbers appear in this document. Phase 0B measures them.

## 1. RPC call map

Only four code paths call Solana RPC. `ingestor/scan.py`, `ingest.py` and `fetch.py` call the StonkFun HTTP API. `pyth.py` calls Pyth Hermes. `prices.py` calls Yahoo Finance. None of these use RPC credits.

| Caller | Trigger | Methods per run | Notes |
| --- | --- | --- | --- |
| `onchain.py` `enrich()` | scheduler, every 6th cycle (every 90 min at the default 900 s interval) | per token: `getTokenLargestAccounts` x1, `getTokenSupply` x1 or x2, `getSignaturesForAddress` x1 (limit 20), `getTransaction` x up to 20, `getAccountInfo` x1 when a pool is set | `top_n=100` tokens by market cap |
| `dbc_collect.py` -> `collectors/meteora-dbc/collector.js` | scheduler, every `DBC_EVERY_CYCLES` cycles (6 in `docker-compose.yml`) | `getSlot` x1, `getProgramAccounts` x (2 per quote mint) + (2 per discovered config) | default method is `getProgramAccounts`, `getProgramAccountsV2` is opt-in through `DBC_RPC_METHOD`; hard cap 1200 requests |
| `server.py` `/api/token/{mint}/refresh` | user request, keyed tier only | same as one token of `onchain.enrich()` | calls `onchain.enrich_token()` |
| `server.py` token image lookup | user request | `getAsset` (DAS) | in-process cache, 24 h TTL, lost on restart |
| `creator_scan.py`, `leaderboard_scan.py` | manual CLI | `getSignaturesForAddress` (100 per page, up to 50 pages), `getTransaction` per signature | not scheduled |
| `launchpad_run.py`, `launchpad_backfill.py` | manual CLI | `getSignaturesForAddress` (1000 per page), `getTransaction` per successful signature | not scheduled, own RPC client |

`helius.py` also defines `getTokenAccountsByOwner`, `getTokenAccountBalance` and `getBalance`. Nothing calls them.

## 2. Credit estimate

Prices used: standard RPC call 1 credit, `getProgramAccounts` 10, `getProgramAccountsV2` 1, DAS 10.

Scheduled onchain run, worst case per token: 1 + 2 + 1 + 20 + 1 = 25 credits. With 100 tokens: up to 2,500 credits per run. At 16 runs per day: up to 40,000 credits per day, about 1.2M per month. That is above the 1M monthly credits of the free plan from this job alone.

Scheduled DBC run with Q quote mints and C configs: 1 + 10 x (2Q + 2C) credits with `getProgramAccounts`. With the 3 configured quotes: 61 + 20C credits per run. C must be read from production. With `getProgramAccountsV2` and P pages the same call costs P credits instead of 10.

Per 15 minute cycle without the onchain or DBC step: 0 RPC credits. RPC load is concentrated in every sixth cycle.

These are upper bounds from code paths. Phase 0B replaces them with measured counts.

## 3. Redundant, sequential or unnecessary calls

1. `onchain._enrich_events` reads the latest 20 signatures of each mint and calls `getTransaction` on all of them every run. It never stores a cursor and never passes `until`. Signatures already classified in `token_events` are fetched again every 90 minutes. This is the largest avoidable cost.
2. `getTokenSupply` is called in `_enrich_holders` and called again inside `_enrich_events` when a burn is found, for the same mint in the same run.
3. Supply, decimals and pool owner change rarely but are refetched every run. No cache exists outside the `getAsset` image lookup.
4. All calls are sequential, one HTTP request per method, behind a global 8 QPS throttle. No JSON-RPC batching is used. `getTransaction`, `getTokenSupply` and `getAccountInfo` across tokens are independent and batchable. `getMultipleAccounts` could replace per-pool `getAccountInfo`.
5. The DBC collector uses `getProgramAccounts` at 10 credits per call by default. `getProgramAccountsV2` is already implemented and costs 1 credit per page.
6. Holders are limited to the 20 accounts returned by `getTokenLargestAccounts`. DAS `getTokenAccounts` (10 credits per page) returns all holders. Adopting it raises cost and only makes sense when full distribution is needed.
7. Enhanced Transactions costs 100 credits per request and is in maintenance mode. It is not a cheaper replacement for `getTransaction` here. Parsed Events (10 credits per request) needs a measured comparison against `getTransaction` plus local parsing before any switch.
8. On 429, `helius.py` sleeps a fixed exponential backoff, ignores `Retry-After` and has no jitter or circuit breaker. `launchpad_backfill.rpc` retries on any error, including non-retryable RPC errors.
9. Errors in `onchain.py` are swallowed by `except Exception: pass`. Failed calls are not counted and a run can report success with no data written.
10. No component counts calls or credits. The heartbeat records step return codes only.

## 4. Repository structure findings

Root has 40 entries. Files that do not belong at the root or need a decision:

- `m1.py`, `m2.py`, `m3.py`, `m4.py`: non-descriptive names. Content: backing chain (M1), token vs terminal-asset movement (M2), stock yield (M3), creator history (M4). Imported by `server.py` and `leaderboard_scan.py`.
- `test_leaderboard_ui.py`: a test outside `tests/`.
- `split_storage.py`, `backup.py`, `snapshot.py`: operational scripts, belong in `scripts/`.
- `creator_scan.py`, `leaderboard_scan.py`, `launchpad_*.py`: CLIs, belong in `scripts/` or `sdb/launchpads/`.
- `scheduler.py` runs `disk_check.sh`, which is not in the repository. Every sixth cycle reports `disk rc` failure and skips the backup in a fresh checkout.
- `launchpad_collect.py` defines `collect_program` twice. The second definition wins.
- `launchpad_collect.py` and `launchpad_backfill.py` each contain their own RPC client, separate from `helius.py`. Phase 1 should route both through one client so counting is complete.
- `ingestor/openapi.json` is a one-line file of unclear purpose.
- Source comments and docstrings are partly in Portuguese.

## 5. Proposed next phases

0B. Add a counting wrapper that only observes (method, status, latency) and run production unchanged for 24 h. Output `bench/baseline-production.json` with aggregates only.
1. One RPC client for all callers: batching, per-method TTL cache, in-cycle dedupe, credit counter, `Retry-After`, jitter, circuit breaker, incremental signatures with `until`. Switch DBC to `getProgramAccountsV2` behind the existing flag. Expose counters in the heartbeat, `/api/rpc-stats` and MCP.
2. Event-driven detection only if the Helius plan allows it.
3. 24 h benchmark on a database copy, `bench/RESULTS.md`, synthetic benchmark.
4. Structure, CI, community files. Separate PR from behavior changes.
5. README and docs.
6. Public reports.
7. PRs, Helius notes, posts.
