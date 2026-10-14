# Tutorial

Run SDB locally in five steps.

## 1. Clone

```sh
git clone https://github.com/Sabadinhos/solana-stock-database.git
cd solana-stock-database
```

## 2. Configure

```sh
cp .env.example .env
```

Set `RPC_URL` to your Solana RPC endpoint. A Helius free plan key works.
Leave it empty to run the API and UI without collection.

## 3. Start the API and UI

```sh
docker compose up -d --build
curl http://127.0.0.1:8090/api/health
```

Open http://127.0.0.1:8090.
The database starts empty.

## 4. Start collection

```sh
docker compose --profile collection up -d
docker compose logs -f scheduler
```

The scheduler runs one cycle every 15 minutes.
On-chain enrichment runs every sixth cycle.

## 5. Check RPC usage

```sh
curl http://127.0.0.1:8090/api/rpc-stats
```

Calls and credits are grouped by day and method.
See [rpc-strategy.md](rpc-strategy.md) for the budget.

## Next

- [Examples](examples/README.md)
- [RPC strategy](rpc-strategy.md)
- [Benchmark](../bench/RESULTS.md)
