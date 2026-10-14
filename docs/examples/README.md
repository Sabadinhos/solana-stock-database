# Examples

Base URL: `https://solanastockdatabase.com` or `http://127.0.0.1:8090`.

| File | Does |
| --- | --- |
| [curl.sh](curl.sh) | Main endpoints |
| [top_tokens.py](top_tokens.py) | Tokens above a market cap |
| [top_tokens.mjs](top_tokens.mjs) | Same, Node 18+ |
| [mcp.json](mcp.json) | MCP config |

| Endpoint | Returns |
| --- | --- |
| `/api/health` | Status |
| `/api/stats` | Totals |
| `/api/search?q=` | Search |
| `/api/token/{mint}` | One token |
| `/api/assets` | Backing assets |
| `/api/cards?limit=` | Token cards |
| `/api/leaderboard/rendimento` | Top payouts |
| `/api/rpc-stats` | RPC credits |
