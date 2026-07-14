import os
from typing import Optional
from supabase import acreate_client, Client
from core.logger import get_logger
from core.metrics import DB_OPERATIONS

logger = get_logger(__name__)

_db_client: Optional[Client] = None

async def init_db(url: str, key: str) -> Client:
    """Initializes the asynchronous Supabase client."""
    global _db_client
    if _db_client is not None:
        return _db_client

    logger.info("db_client_initializing", url=url)
    try:
        _db_client = await acreate_client(url, key)
        logger.info("db_client_initialized_successfully")
        return _db_client
    except Exception as e:
        logger.exception("db_client_initialization_failed", error=str(e))
        raise

def get_db() -> Client:
    """Returns the initialized database client."""
    if _db_client is None:
        raise RuntimeError("Database client is not initialized. Call init_db first.")
    return _db_client

async def record_db_op(table: str, operation: str, coro):
    """Helper to execute a database coroutine, record metrics, and log failures."""
    try:
        res = await coro
        DB_OPERATIONS.labels(table=table, operation=operation, status="success").inc()
        return res
    except Exception as e:
        DB_OPERATIONS.labels(table=table, operation=operation, status="failure").inc()
        logger.error(
            "db_operation_failed",
            table=table,
            operation=operation,
            error=str(e)
        )
        raise
