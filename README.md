# OpenGrok MCP Server

MCP server for [OpenGrok](https://oracle.github.io/opengrok/) that lets AI agents search and read indexed source code.

## 中文说明

### 1. 项目用途

这个项目把 OpenGrok 的 REST API 封装成 MCP 工具，方便 Claude / ChatGPT / 自研 Agent 直接进行代码检索、文件读取、符号查询、版本对比等操作。

### 2. 主要能力

- `search`: 基础检索（全文、定义、引用、路径）
- `search_enhanced`: 支持分页、文件类型过滤和摘要输出
- `search_symbols_global`: 跨项目符号定义/引用查询
- `get_file`: 读取文件原文
- `get_defs`: 获取文件内定义信息
- `get_history`: 查看文件或目录历史
- `get_annotations`: 查看 blame/注释信息
- `list_directory`: 列目录
- `list_projects`: 列所有项目
- `compare_revisions`: 比较两个版本并输出 diff
- `get_suggestions`: 前缀联想建议
- `health_check`: 服务与 OpenGrok 连通性自检

### 3. 性能与稳定性优化

- 复用单个 `httpx.AsyncClient`（连接池 + keep-alive）
- 对 429/5xx 与网络异常进行指数退避重试
- 可配置内存 TTL 缓存，减少重复查询开销
- 对查询参数做边界约束，避免超大请求影响服务

### 4. 快速开始

```bash
pip install -r requirements.txt
python server.py --transport stdio
```

SSE 模式：

```bash
python server.py --transport sse --host 0.0.0.0 --port 8081
```

Streamable HTTP 模式：

```bash
python server.py --transport streamable-http --host 0.0.0.0 --port 8081
```

### 5. 关键配置

基础配置：

- `OPENGROK_URL` (默认: `http://localhost:8080/source`)
- `MCP_TRANSPORT` (默认: `stdio`)
- `HOST` (默认: `0.0.0.0`)
- `PORT` / `MCP_PORT` (默认: `8081`)

HTTP 客户端配置：

- `OPENGROK_TIMEOUT_SECONDS` (默认: `30`)
- `OPENGROK_HTTP_RETRIES` (默认: `2`)
- `OPENGROK_HTTP_RETRY_BACKOFF_SECONDS` (默认: `0.25`)
- `OPENGROK_HTTP_MAX_CONNECTIONS` (默认: `100`)
- `OPENGROK_HTTP_MAX_KEEPALIVE_CONNECTIONS` (默认: `20`)

缓存与限制：

- `OPENGROK_CACHE_TTL_SECONDS` (默认: `10`，设为 `0` 可关闭缓存)
- `OPENGROK_CACHE_MAX_ENTRIES` (默认: `256`)
- `OPENGROK_MAX_RESULTS_CAP` (默认: `500`)

Host Header 安全校验（streamable-http / sse）：

- `MCP_ALLOWED_HOSTS` 逗号分隔白名单，格式如 `192.168.12.172:*`、`example.com:8081`
- `MCP_ALLOWED_ORIGINS` 逗号分隔 Origin 白名单，格式如 `http://192.168.12.172:*`
- `MCP_DISABLE_DNS_REBINDING_PROTECTION` 设为 `true/1` 可关闭校验（仅内网排障时建议临时使用）

### 6. 代码结构

```text
.
|-- server.py                 # 轻量启动入口
|-- opengrok_mcp/
|   |-- app.py                # 应用装配与启动逻辑
|   |-- config.py             # 环境变量与配置读取
|   |-- api_client.py         # OpenGrok API 客户端（重试/缓存/连接池）
|   |-- tools.py              # MCP 工具注册与业务逻辑
|   |-- utils.py              # 通用工具函数
|   `-- __init__.py
|-- test_probe.py             # 基础 HTTP 探活
|-- test_http.py              # SSE 模式测试
`-- test_deploy.py            # Streamable HTTP 模式测试
```

### 7. 测试脚本

```bash
python test_probe.py
python test_http.py
python test_deploy.py
```

可选环境变量：

- `MCP_BASE_URL` (默认 `http://localhost:8081`)
- `MCP_SSE_URL` (默认 `${MCP_BASE_URL}/sse`)
- `MCP_STREAMABLE_HTTP_URL` (默认 `${MCP_BASE_URL}/mcp`)

## English Notes

This repository is now modularized:

- `server.py` is only the entrypoint.
- Runtime and wiring live in `opengrok_mcp/app.py`.
- Environment-driven config is in `opengrok_mcp/config.py`.
- OpenGrok HTTP logic is in `opengrok_mcp/api_client.py`.
- MCP tools are defined in `opengrok_mcp/tools.py`.
