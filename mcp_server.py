"""SDB – servidor MCP (JSON-RPC 2.0 sobre stdio, stdlib puro).

Cliente remoto da API hospedada: a tool do MCP chama os MESMOS endpoints da web,
provando o argumento "um motor, duas portas". Roda na máquina do cliente, então
não lê o SQLite do VPS; chama a API.

Env:
  SDB_API_URL  (padrão http://localhost:8090) – URL pública da API
  SDB_API_KEY  (opcional) – chave do tier pago (Authorization: Bearer)

Uso (Claude Desktop / Claude Code / Cursor):
  python mcp_server.py

Bloco de config para Claude Desktop (claude_desktop_config.json):
  {"mcpServers": {"sdb": {"command": "python",
     "args": ["/caminho/para/mcp_server.py"],
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
     "description": "Busca memstocks por nome, símbolo ou mint.",
     "inputSchema": _schema({
         "q": {"type": "string", "description": "termo de busca"},
         "limit": {"type": "integer", "description": "máx resultados (30)"},
     }, ["q"])},
    {"name": "get_token",
     "description": "Métricas de um memstock: lastro (M1), rendimento em ação (M3) e criador (M4).",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "endereço do mint"},
     }, ["mint"])},
    {"name": "get_decomposition",
     "description": "Separa o movimento USD do token do movimento do ativo terminal, quando há série Pyth persistida.",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "endereço do mint"},
         "window": {"type": "integer", "description": "janela em dias (7)"},
     }, ["mint"])},
    {"name": "get_dbc",
     "description": "Launch Passport Meteora DBC de um token, usando somente pools persistidos com correspondência exata de mint.",
     "inputSchema": _schema({
         "mint": {"type": "string", "description": "endereço do mint"},
         "limit": {"type": "integer", "description": "máx pools (20)"},
     }, ["mint"])},
    {"name": "get_dbc_pool",
     "description": "Detalhes e snapshots históricos de um pool Meteora DBC persistido.",
     "inputSchema": _schema({
         "address": {"type": "string", "description": "endereço do pool"},
     }, ["address"])},
    {"name": "get_news",
     "description": "Evidências editoriais com fonte original; vazio quando nenhum feed verificado está configurado.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "máx itens (30)"},
         "asset": {"type": "string", "description": "filtro opcional de asset"},
     }, [])},
    {"name": "list_curated_creators",
     "description": "Registry de identidades de creators somente quando existe fonte curada verificável.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "máx itens (50)"},
     }, [])},
    {"name": "get_creator",
     "description": "Histórico de uma carteira criadora: lançamentos, graduados, pico.",
     "inputSchema": _schema({
         "creator": {"type": "string", "description": "endereço da carteira"},
     }, ["creator"])},
    {"name": "list_assets",
     "description": "Ativos terminais (xStocks, PreStocks) com contagem e yield.",
     "inputSchema": _schema({}, [])},
    {"name": "get_attention",
     "description": "Índice de atenção: lançamentos por ativo terminal na janela.",
     "inputSchema": _schema({
         "days": {"type": "integer", "description": "janela em dias (7)"},
     }, [])},
    {"name": "get_survival",
     "description": "Taxa de graduação e drawdown por categoria de quote.",
     "inputSchema": _schema({}, [])},
    {"name": "leaderboard_rendimento",
     "description": "Quais memstocks mais pagaram no ativo subjacente (M3).",
     "inputSchema": _schema({
         "category": {"type": "string", "description": "categoria (xstock)"},
         "limit": {"type": "integer", "description": "máx (50)"},
     }, [])},
    {"name": "top_tokens",
     "description": "Top N memstocks (stock tokens) por market cap. Use para perguntas como 'top 10 stock tokens hoje'.",
     "inputSchema": _schema({
         "limit": {"type": "integer", "description": "máx resultados (10)"},
         "category": {"type": "string", "description": "filtro opcional: xstock, prestock"},
     }, [])},
    {"name": "get_stats",
     "description": "Sistema vivo: snapshots coletados, tokens, recompensas.",
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
    raise ValueError(f"tool desconhecida: {name}")


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
