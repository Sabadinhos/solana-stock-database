# Examples

All examples use the public API. Replace the base URL with `http://127.0.0.1:8090` for a local run.

| File | What it does |
| --- | --- |
| [curl.sh](curl.sh) | Common endpoints from the shell. |
| [top_tokens.py](top_tokens.py) | Prints tokens above a market cap floor. Python stdlib only. |
| [top_tokens.mjs](top_tokens.mjs) | Same in Node 18+. No dependencies. |
| [mcp.json](mcp.json) | MCP client config for agents. |

## Endpoints

| Endpoint | Returns |
| --- | --- |
| `GET /api/health` | Service status. |
| `GET /api/stats` | Token count and total market cap. |
| `GET /api/search?q=` | Tokens matching a symbol, name or mint. |
| `GET /api/token/{mint}` | One token with holders and events. |
| `GET /api/assets` | Backing assets and their tokens. |
| `GET /api/cards?limit=` | Token cards for the UI. |
| `GET /api/leaderboard/rendimento?limit=` | Tokens ranked by payout yield. |
| `GET /api/rpc-stats` | RPC calls and credits per day and method. |
