import argparse
import asyncio
import logging
import os
from typing import Tuple

from mcp.server.fastmcp import FastMCP

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


def create_app() -> Tuple[FastMCP, OpenGrokApiClient, ServerConfig, logging.Logger]:
    config = ServerConfig.from_env()
    logger = configure_logging(config.log_level)

    mcp = FastMCP("opengrok-mcp")
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
    mcp, api_client, config, logger = create_app()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    logger.info(
        "Starting OpenGrok MCP Server on %s:%d with transport=%s",
        args.host,
        args.port,
        args.transport,
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
