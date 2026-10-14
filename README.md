# Solana Stock Database (SDB)

Read-only data for Solana memstocks. REST API and MCP.

<p align="center"><img src="docs/assets/hero.png" alt="SDB home" width="900"></p>

<p align="center"><a href="https://solanastockdatabase.com">Live site</a> &middot; <a href="docs/tutorial.md">Tutorial</a> &middot; <a href="docs/examples/README.md">Examples</a> &middot; <a href="docs/rpc-strategy.md">RPC</a> &middot; <a href="LICENSE">MIT</a></p>

## Your RPC

```sh
cp .env.example .env
```

Set `RPC_URL` in `.env`:

```sh
RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
```

- Empty: API and UI run, onchain collection is off.
- `.env` is git-ignored.

> **Tested only with Helius.** The free plan is enough.

## What you get

<p align="center"><img src="docs/assets/tokens.png" alt="Token cards" width="900"></p>

- StonkFun memstocks: market cap, volume, holders, payouts.
- Backing stocks: SPY, NVDA, GLD, AAPL and more.
- REST API and MCP server.
- RPC credits tracked per method.

## Run

```sh
docker compose up -d --build
```

Open `http://127.0.0.1:8090`. Collection: `docker compose --profile collection up -d`.

## Test

```sh
python -m unittest discover -s tests
```

## License

MIT.
