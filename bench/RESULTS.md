# Benchmark results

## Synthetic benchmark

Reproduce:

```sh
python bench/synthetic.py --tokens 100 --runs 16 --mean-new 3 --seed 7
python bench/synthetic.py --tokens 100 --runs 16 --mean-new 15 --seed 7
```

The script simulates one day of the onchain step (16 runs at the default 90 minute cadence) against an in-memory chain. Each run starts with an empty cache, as each scheduled run is a separate process. About 10% of simulated transactions fail. It needs no network and no RPC key.

| Scenario | Strategy | RPC credits | getTransaction calls | Valid events stored | Events from failed tx |
| --- | --- | ---: | ---: | ---: | ---: |
| 3 new signatures per token per run | legacy | 31,811 | 25,411 | 288 | 41 |
| 3 new signatures per token per run | incremental | 9,110 | 4,210 | 288 | 0 |
| 15 new signatures per token per run | legacy | 37,356 | 30,956 | 1,319 | 158 |
| 15 new signatures per token per run | incremental | 26,508 | 21,096 | 1,477 | 0 |

Credit reduction: 71.4% at low activity, 29.0% at high activity.

Window: the incremental strategy stored every valid event the legacy strategy stored. At high activity it stored more, because legacy only reads the latest 20 signatures per run and skips anything older, while incremental pages back to the stored cursor (up to `SDB_ONCHAIN_MAX_PAGES` pages). Legacy also stored events from failed transactions, which did not change chain state.

Where the savings come from:

1. Signatures already processed are not fetched again (`until` cursor per mint).
2. Failed transactions are skipped before `getTransaction`.
3. Pool owner is refreshed once per 24 h instead of every run.

The saving shrinks as activity grows, because then most signatures are new and must be read.

## Production

Not measured yet. Since this change, every collector run writes per-method calls and credits to `data/rpc-stats.json`, exposed at `GET /api/rpc-stats` and the MCP tool `get_rpc_stats`. A production comparison will be added here once 24 h of each strategy have been recorded. Until then, no production reduction is claimed.
