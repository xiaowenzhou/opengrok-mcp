import logging
import os
from dataclasses import dataclass


LOGGER = logging.getLogger("opengrok-mcp")


def read_int_env(
    name: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("Invalid integer %s=%r, using default %d", name, raw, default)
        return default
    if value < min_value:
        LOGGER.warning("%s=%d is too small, clamping to %d", name, value, min_value)
        return min_value
    if value > max_value:
        LOGGER.warning("%s=%d is too large, clamping to %d", name, value, max_value)
        return max_value
    return value


def read_float_env(
    name: str,
    default: float,
    min_value: float,
    max_value: float,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("Invalid float %s=%r, using default %.2f", name, raw, default)
        return default
    if value < min_value:
        LOGGER.warning("%s=%.2f is too small, clamping to %.2f", name, value, min_value)
        return min_value
    if value > max_value:
        LOGGER.warning("%s=%.2f is too large, clamping to %.2f", name, value, max_value)
        return max_value
    return value


@dataclass(frozen=True)
class ServerConfig:
    log_level: str
    opengrok_url: str
    opengrok_api_url: str
    request_timeout_seconds: float
    http_retries: int
    http_retry_backoff_seconds: float
    http_max_connections: int
    http_max_keepalive_connections: int
    cache_ttl_seconds: float
    cache_max_entries: int
    max_results_cap: int

    @classmethod
    def from_env(cls) -> "ServerConfig":
        opengrok_url = os.environ.get("OPENGROK_URL", "http://localhost:8080/source").rstrip(
            "/"
        )

        http_max_connections = read_int_env(
            "OPENGROK_HTTP_MAX_CONNECTIONS",
            default=100,
            min_value=1,
            max_value=1000,
        )
        http_max_keepalive_connections = read_int_env(
            "OPENGROK_HTTP_MAX_KEEPALIVE_CONNECTIONS",
            default=20,
            min_value=1,
            max_value=1000,
        )
        if http_max_keepalive_connections > http_max_connections:
            http_max_keepalive_connections = http_max_connections

        return cls(
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            opengrok_url=opengrok_url,
            opengrok_api_url=f"{opengrok_url}/api/v1",
            request_timeout_seconds=read_float_env(
                "OPENGROK_TIMEOUT_SECONDS",
                default=30.0,
                min_value=1.0,
                max_value=300.0,
            ),
            http_retries=read_int_env(
                "OPENGROK_HTTP_RETRIES",
                default=2,
                min_value=0,
                max_value=10,
            ),
            http_retry_backoff_seconds=read_float_env(
                "OPENGROK_HTTP_RETRY_BACKOFF_SECONDS",
                default=0.25,
                min_value=0.05,
                max_value=10.0,
            ),
            http_max_connections=http_max_connections,
            http_max_keepalive_connections=http_max_keepalive_connections,
            cache_ttl_seconds=read_float_env(
                "OPENGROK_CACHE_TTL_SECONDS",
                default=10.0,
                min_value=0.0,
                max_value=3600.0,
            ),
            cache_max_entries=read_int_env(
                "OPENGROK_CACHE_MAX_ENTRIES",
                default=256,
                min_value=1,
                max_value=10000,
            ),
            max_results_cap=read_int_env(
                "OPENGROK_MAX_RESULTS_CAP",
                default=500,
                min_value=1,
                max_value=10000,
            ),
        )
