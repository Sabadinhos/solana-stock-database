# Benchmark

```sh
python bench/synthetic.py --tokens 100 --runs 16 --mean-new 3 --seed 7
python bench/synthetic.py --tokens 100 --runs 16 --mean-new 15 --seed 7
```

One simulated day. No network, no RPC key.

| New sigs/run | Legacy credits | Incremental credits | Cut |
| --- | ---: | ---: | ---: |
| 3 | 31,811 | 9,110 | 71.4% |
| 15 | 37,356 | 26,508 | 29.0% |

No valid event lost. Production numbers: `GET /api/rpc-stats`.
