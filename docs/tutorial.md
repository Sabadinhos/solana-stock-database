# Tutorial

## 1. Clone

```sh
git clone https://github.com/Sabadinhos/solana-stock-database.git
cd solana-stock-database
```

## 2. Configure

```sh
cp .env.example .env
```

Set `RPC_URL`. Helius free plan works.

## 3. Run

```sh
docker compose up -d --build
curl http://127.0.0.1:8090/api/health
```

## 4. Collect

```sh
docker compose --profile collection up -d
```

One cycle every 15 minutes. Onchain every 6 cycles.

## 5. Check credits

```sh
curl http://127.0.0.1:8090/api/rpc-stats
```

Next: [Examples](examples/README.md)
