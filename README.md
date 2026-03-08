# OpenGrok MCP Server

MCP server for [OpenGrok](https://oracle.github.io/opengrok/) that lets AI agents search and read indexed source code.

## Features

- `search`: full text / definitions / references / path queries.
- `search_enhanced`: filtered + paginated search with optional summarization.
- `search_symbols_global`: cross-project symbol lookup.
- `get_file`: fetch raw file content.
- `get_defs`: fetch symbol definitions of a file.
- `get_history`: fetch history for file or directory.
- `get_annotations`: fetch blame/annotation data.
- `list_directory`: list directory entries.
- `list_projects`: list indexed projects.
- `compare_revisions`: unified diff between two revisions.
- `get_suggestions`: query suggestions/autocomplete.
- `health_check`: runtime config + OpenGrok reachability.

## Performance Optimizations

- Reuses a single async `httpx` client (connection pooling + keep-alive).
- Retries transient HTTP/network failures with exponential backoff.
- Optional in-memory TTL cache for repeated OpenGrok API reads.
- Parameter clamping to avoid accidental overly large requests.

## Requirements

- Python 3.10+
- OpenGrok instance with REST API enabled

Install:

```bash
pip install -r requirements.txt
```

## Configuration

### Core

- `OPENGROK_URL` (default: `http://localhost:8080/source`)
- `MCP_TRANSPORT` (default: `stdio`; options: `stdio`, `sse`, `streamable-http`)
- `HOST` (default: `0.0.0.0`)
- `PORT` or `MCP_PORT` (default: `8081`)

### HTTP Client

- `OPENGROK_TIMEOUT_SECONDS` (default: `30`)
- `OPENGROK_HTTP_RETRIES` (default: `2`)
- `OPENGROK_HTTP_RETRY_BACKOFF_SECONDS` (default: `0.25`)
- `OPENGROK_HTTP_MAX_CONNECTIONS` (default: `100`)
- `OPENGROK_HTTP_MAX_KEEPALIVE_CONNECTIONS` (default: `20`)

### Cache and Limits

- `OPENGROK_CACHE_TTL_SECONDS` (default: `10`; set `0` to disable cache)
- `OPENGROK_CACHE_MAX_ENTRIES` (default: `256`)
- `OPENGROK_MAX_RESULTS_CAP` (default: `500`)

## Run

### stdio

```bash
python server.py --transport stdio
```

### SSE

```bash
python server.py --transport sse --host 0.0.0.0 --port 8081
```

### Streamable HTTP

```bash
python server.py --transport streamable-http --host 0.0.0.0 --port 8081
```

## Quick Checks

- `python test_probe.py`
- `python test_http.py`
- `python test_deploy.py`

Optional test overrides:

- `MCP_BASE_URL` (default `http://localhost:8081`)
- `MCP_SSE_URL` (default `${MCP_BASE_URL}/sse`)
- `MCP_STREAMABLE_HTTP_URL` (default `${MCP_BASE_URL}/mcp`)
