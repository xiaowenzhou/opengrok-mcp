# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenGrok MCP Server — wraps the OpenGrok REST API as MCP (Model Context Protocol) tools so AI agents can search and browse code indexed by OpenGrok. Built with FastMCP, httpx, and uvicorn.

## Commands

### Install & Run
```bash
pip install -r requirements.txt
python server.py --transport stdio                                          # default
python server.py --transport sse --host 0.0.0.0 --port 8081                # SSE
python server.py --transport streamable-http --host 0.0.0.0 --port 8081    # streamable HTTP
```

### Tests
No pytest. Tests are standalone scripts that require a running server:
```bash
python test_probe.py       # raw HTTP connectivity check
python test_http.py        # SSE transport integration test
python test_deploy.py      # streamable-http transport integration test
```
Configure test target via `MCP_BASE_URL`, `MCP_SSE_URL`, or `MCP_STREAMABLE_HTTP_URL` env vars (default: `http://localhost:8081`).

## Architecture

**Entry flow:** `server.py` → `app.main()` → `create_app()` → `FastMCP.run(transport=...)`

Four core modules under `opengrok_mcp/`:

- **app.py** — CLI arg parsing, logging setup, transport security config (DNS rebinding protection, host/origin whitelisting), app assembly via `create_app()`, and `main()` entry point.
- **config.py** — `ServerConfig` dataclass populated entirely from environment variables. All numeric values are validated and clamped with `read_int_env()`/`read_float_env()`. Supports Bearer token and Basic Auth.
- **api_client.py** — `OpenGrokApiClient` wrapping a lazily-initialized `httpx.AsyncClient` with connection pooling, exponential backoff retry (429/5xx), and an `OrderedDict`-based LRU cache with TTL expiration. Thread-safe via `asyncio.Lock`.
- **tools.py** — 11 MCP tools registered via `@mcp.tool()` decorators (search, search_enhanced, search_symbols_global, get_file, get_defs, get_history, get_annotations, list_directory, list_projects, compare_revisions, get_suggestions) plus `health_check`.
- **utils.py** — Pure helpers: path/endpoint normalization, HTML stripping, cache key generation, result formatting with truncation.

**Key design decisions:**
- Async throughout; single `httpx.AsyncClient` instance with double-checked locking for lazy init.
- All configuration is env-var driven with sensible defaults — no config files.
- Transport security (allowed hosts/origins, DNS rebinding protection) is configurable for HTTP transports via `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS`, `MCP_DISABLE_DNS_REBINDING_PROTECTION`.
- Result capping (`OPENGROK_MAX_RESULTS_CAP`) prevents unbounded memory usage from large search results.
