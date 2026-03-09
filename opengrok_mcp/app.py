import argparse
import asyncio
import logging
import os
from typing import List, Tuple

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .api_client import OpenGrokApiClient
from .config import ServerConfig
from .tools import register_tools


LOGGER_NAME = "opengrok-mcp"


def configure_logging(log_level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger(LOGGER_NAME)


def parse_csv_env(name: str) -> List[str]:
    raw = os.environ.get(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_transport_security(host: str, port: int) -> TransportSecuritySettings:
    if read_bool_env("MCP_DISABLE_DNS_REBINDING_PROTECTION", default=False):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    allowed_hosts = set(parse_csv_env("MCP_ALLOWED_HOSTS"))
    allowed_origins = set(parse_csv_env("MCP_ALLOWED_ORIGINS"))

    allowed_hosts.update({"127.0.0.1:*", "localhost:*", "[::1]:*"})
    allowed_origins.update(
        {"http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"}
    )

    # For non-wildcard bind addresses, allow the bound host by default.
    if host not in {"0.0.0.0", "::"}:
        allowed_hosts.add(f"{host}:*")
        allowed_hosts.add(f"{host}:{port}")
        allowed_origins.add(f"http://{host}:*")
        allowed_origins.add(f"http://{host}:{port}")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


def create_app(host: str, port: int) -> Tuple[FastMCP, OpenGrokApiClient, ServerConfig, logging.Logger]:
    config = ServerConfig.from_env()
    logger = configure_logging(config.log_level)

    mcp = FastMCP(
        "opengrok-mcp",
        host=host,
        port=port,
        transport_security=build_transport_security(host, port),
    )
    api_client = OpenGrokApiClient(
        base_url=config.opengrok_api_url,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.http_retries,
        retry_backoff_seconds=config.http_retry_backoff_seconds,
        max_connections=config.http_max_connections,
        max_keepalive_connections=config.http_max_keepalive_connections,
        cache_ttl_seconds=config.cache_ttl_seconds,
        cache_max_entries=config.cache_max_entries,
        logger=logger,
    )
    register_tools(mcp, api_client, config)
    return mcp, api_client, config, logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenGrok MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", os.environ.get("MCP_PORT", 8081))),
        help="Port (default: 8081, can be overridden by PORT or MCP_PORT)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Host to bind (default: 0.0.0.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mcp, api_client, config, logger = create_app(args.host, args.port)

    logger.info(
        "Starting OpenGrok MCP Server on %s:%d with transport=%s",
        args.host,
        args.port,
        args.transport,
    )
    if mcp.settings.transport_security:
        logger.info(
            "Transport security: dns_rebinding=%s allowed_hosts=%s",
            mcp.settings.transport_security.enable_dns_rebinding_protection,
            ",".join(mcp.settings.transport_security.allowed_hosts),
        )
    logger.info("OpenGrok API URL: %s", config.opengrok_api_url)
    logger.info(
        "HTTP timeout=%ss retries=%d backoff=%ss pool=%d keepalive=%d cache_ttl=%ss cache_size=%d",
        config.request_timeout_seconds,
        config.http_retries,
        config.http_retry_backoff_seconds,
        config.http_max_connections,
        config.http_max_keepalive_connections,
        config.cache_ttl_seconds,
        config.cache_max_entries,
    )

    try:
        if args.transport == "streamable-http":
            mcp.run(transport="streamable-http")
        elif args.transport == "sse":
            mcp.run(transport="sse")
        else:
            mcp.run(transport="stdio")
    except Exception:
        logger.exception("Server terminated with error")
        raise
    finally:
        try:
            asyncio.run(api_client.close())
        except RuntimeError:
            pass
