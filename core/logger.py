import sys
import os
import logging
import structlog
from typing import Any

def setup_logger(json_format: bool = True) -> None:
    """Configures structured logging for the trading bot.
    Logs JSON to standard output, suitable for Grafana Loki ingestion.
    """
    # Configure base logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )

    processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
