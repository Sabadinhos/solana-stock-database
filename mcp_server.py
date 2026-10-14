"""SDB: MCP server (JSON-RPC 2.0 over stdio, pure stdlib).

Remote client of the hosted API: MCP tools call the SAME endpoints as the web app,
proving the "one engine, two doors" argument. Runs on the client machine, so it
does not read the VPS SQLite; it calls the API.

Env:
  SDB_API_URL  (default http://localhost:8090): public API URL
  SDB_API_KEY  (optional): paid tier key (Authorization: Bearer)

Usage (Claude Desktop / Claude Code / Cursor):
  python mcp_server.py

Config block for Claude Desktop (claude_desktop_config.json):
  {"mcpServers": {"sdb": {"command": "python",
     "args": ["/path/to/mcp_server.py"],
     "env": {"SDB_API_URL": "http://localhost:8090"}}}}
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_URL = os.environ.get("SDB_API_URL", "http://localhost:8090").rstrip("/")
API_KEY = os.environ.get("SDB_API_KEY", "")

PROTOCOL_VERSION = "2024-11-05"


def _schema(props, required):
    return {"type": "object", "properties": props, "required": required}


TOOLS = [
    {"name": "search_tokens",
     "description": "Search memstocks by name, symbol or mint.",
     "inputSchema": _schema({
         "q": {"type": "string", "description": "search term"},
         "limit": {"type": "integer", "description": "max results (30)"},
     }, ["q"])},
    {"name": "get_token",
     "description": "Memstock metrics: backing (M1), yield in stock (M3) and creator (M4).",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "mint address"},
     }, ["mint"])},
    {"name": "get_decomposition",
     "description": "Separates the token USD move from the terminal asset move, when a persisted Pyth series exists.",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "mint address"},
         "window": {"type": "integer", "description": "window in days (7)"},
     }, ["mint"])},
    {"name": "get_dbc",
     "description": "Meteora DBC Launch Passport for a token, using only persisted pools with an exact mint match.",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "mint address"},
         "limit": {"type": "integer", "description": "max pools (20)"},
     }, ["mint"])},
    {"name": "get_dbc_pool",
     "description": "Details and historical snapshots of a persisted Meteora DBC pool.",
     "inputSchema": _schema({
         "address": {"type": "string", "description": "pool address"},
     }, ["address"])},
    {"name": "get_rpc_stats",
     "description": "RPC calls, estimated Helius credits, 429s and cache hits per method and per day.",
     "inputSchema": _schema({}, [])},
    {"name": "get_news",
     "description": "Editorial evidence with original source; empty when no verified feed is configured.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "max items (30)"},
         "asset": {"type": "string", "description": "optional asset filter"},
     }, [])},
    {"name": "list_curated_creators",
     "description": "Creator identity registry, only when a verifiable curated source exists.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "max items (50)"},
     }, [])},
    {"name": "get_creator",
     "description": "Creator wallet history: launches, graduated, peak.",
     "inputSchema": _schema({
         "creator": {"type": "string", "description": "wallet address"},
     }, ["creator"])},
    {"name": "list_assets",
     "description": "Terminal assets (xStocks, PreStocks) with counts and yield.",
     "inputSchema": _schema({}, [])},
    {"name": "get_attention",
     "description": "Attention index: launches per terminal asset in the window.",
     "inputSchema": _schema({
         "days": {"type": "integer", "description": "window in days (7)"},
     }, [])},
    {"name": "get_survival",
     "description": "Graduation rate and drawdown by quote category.",
     "inputSchema": _schema({}, [])},
    {"name": "leaderboard_rendimento",
     "description": "Which memstocks paid the most in the underlying asset (M3).",
     "inputSchema": _schema({
         "category": {"type": "string", "description": "categoria (xstock)"},
         "limit": {"type": "integer", "description": "max (50)"},
     }, [])},
    {"name": "top_tokens",
     "description": "Top N memstocks (stock tokens) by market cap. Use for questions like 'top 10 stock tokens today'.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "max results (10)"},
         "category": {"type": "string", "description": "optional filter: xstock, prestock"},
     }, [])},
    {"name": "get_stats",
     "description": "Live system: collected snapshots, tokens, rewards.",
     "inputSchema": _schema({}, [])},
]


def api_get(path):
    req = urllib.request.Request(API_URL + path, headers={"Accept": "application/json", "User-Agent": "SDB-MCP/0.1"})
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def call_tool(name, args):
    a = args or {}
    q = urllib.parse.quote
    if name == "search_tokens":
        return api_get(f"/api/search?q={q(str(a.get('q','')))}&limit={a.get('limit', 30)}")
    if name == "get_token":
        return api_get(f"/api/token/{a['mint']}")
    if name == "get_decomposition":
        path = f"/api/token/{q(a['mint'])}"
        if a.get("window") is not None:
            path += f"?window={int(a['window'])}"
        payload = api_get(path)
        return {"mint": a["mint"], "decomposition": payload.get("decomposition")}
    if name == "get_dbc":
        return api_get(f"/api/token/{q(a['mint'])}/dbc?limit={a.get('limit', 20)}")
    if name == "get_dbc_pool":
        return api_get(f"/api/dbc/pool/{q(a['address'])}")
    if name == "get_rpc_stats":
        return api_get("/api/rpc-stats")
    if name == "get_news":
        path = f"/api/news?limit={a.get('limit', 30)}"
        if a.get('asset'):
            path += f"&asset={q(a['asset'])}"
        return api_get(path)
    if name == "list_curated_creators":
        return api_get(f"/api/creators/registry?limit={a.get('limit', 50)}")
    if name == "get_creator":
        return api_get(f"/api/creator/{a['creator']}")
    if name == "list_assets":
        return api_get("/api/assets")
    if name == "get_attention":
        return api_get(f"/api/attention?days={a.get('days', 7)}")
    if name == "get_survival":
        return api_get("/api/survival")
    if name == "leaderboard_rendimento":
        return api_get(
            f"/api/leaderboard/rendimento?category={a.get('category', 'xstock')}"
            f"&limit={a.get('limit', 50)}")
    if name == "top_tokens":
        return api_get(f"/api/cards?sort=mc&limit={a.get('limit', 10)}")
    if name == "get_stats":
        return api_get("/api/stats")
    raise ValueError(f"unknown tool: {name}")


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sdb", "version": "0.1"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        try:
            result = call_tool(name, args)
            text = json.dumps(result, ensure_ascii=False)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            text = json.dumps({"error": str(e)}, ensure_ascii=False)
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}], "isError": False}}
    if method == "notifications/initialized":
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": "method not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
