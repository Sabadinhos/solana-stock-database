# Solana Stock Database (SDB)

## Overview

SDB indexes Solana memstock and stock-token activity. It stores observations and history in a local SQLite database. It serves that data over REST and MCP.

SDB is read-only. It is not a wallet or trading system.

## Helius signals

`helius.py` calls these Helius methods:

- `getAsset`
- `getTokenLargestAccounts`
- `getTokenSupply`
- `getTokenAccountsByOwner`
- `getAccountInfo`
- `getTokenAccountBalance`
- `getBalance`
- `getSignaturesForAddress`
- `getTransaction`

`onchain.py` stores largest-account and holder-concentration snapshots. It parses confirmed transactions for initialize, mint, burn, authority, and fee events. It also records the program that owns a pool account. SDB does not use Helius webhooks.

## Run locally

Requires Docker Compose.

```sh
cp .env.example .env
docker compose up --build
```

Open `http://127.0.0.1:8090`. SDB creates an empty SQLite database on startup. The default Compose setup starts only the API and UI, bound to localhost.

Collection is opt-in. Enable the `collection` Compose profile after adding provider settings to `.env`. RPC use may incur provider charges.

## Tests

Tests use synthetic data.

```sh
python -m unittest discover -s tests -v
npm --prefix collectors/meteora-dbc ci
npm --prefix collectors/meteora-dbc test
```

## Data and security

The repository contains source code, schema, synthetic tests, and a DBC collector. It contains no production database, API keys, wallets, or customer data. Never commit `.env` or local database files.

## License

MIT. See [LICENSE](LICENSE).
