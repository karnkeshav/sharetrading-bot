from prometheus_client import Counter, Gauge, Histogram, start_http_server
from typing import Optional
from core.logger import get_logger

logger = get_logger(__name__)

# Prometheus metrics definitions
HEARTBEAT_TIMESTAMP = Gauge(
    "trading_bot_heartbeat_timestamp",
    "Epoch timestamp of the last successful executor cycle"
)

TICKS_PROCESSED = Counter(
    "trading_bot_ticks_processed_total",
    "Total number of market ticks processed",
    ["symbol"]
)

DB_OPERATIONS = Counter(
    "trading_bot_db_operations_total",
    "Total database operations performed",
    ["table", "operation", "status"]
)

REDIS_OPERATIONS = Counter(
    "trading_bot_redis_operations_total",
    "Total Redis operations performed",
    ["operation", "status"]
)

ACTIVE_POSITIONS = Gauge(
    "trading_bot_active_positions",
    "Number of currently open/monitored positions",
    ["symbol"]
)

DAILY_PNL_PCT = Gauge(
    "trading_bot_daily_pnl_percentage",
    "Current daily profit and loss in percentage (tracks risk limit)"
)

CYCLE_LATENCY = Histogram(
    "trading_bot_cycle_latency_seconds",
    "Time taken to run a full execution loop cycle",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)
)

ERROR_COUNT = Counter(
    "trading_bot_errors_total",
    "Total errors encountered in execution loop",
    ["module", "error_type"]
)

def start_metrics_server(port: int = 8000) -> None:
    """Starts the Prometheus HTTP metrics server."""
    try:
        start_http_server(port)
        logger.info("metrics_server_started", port=port)
    except Exception as e:
        logger.exception("metrics_server_failed_to_start", error=str(e))
        raise
