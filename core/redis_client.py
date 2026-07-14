import redis.asyncio as aioredis
from typing import Optional, Any
from core.logger import get_logger
from core.metrics import REDIS_OPERATIONS

logger = get_logger(__name__)

_redis_pool: Optional[aioredis.ConnectionPool] = None

def init_redis(host: str, port: int, db: int = 0, password: Optional[str] = None) -> None:
    """Initializes the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        return
        
    logger.info("redis_pool_initializing", host=host, port=port, db=db)
    _redis_pool = aioredis.ConnectionPool(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=True
    )
    logger.info("redis_pool_initialized_successfully")

def get_redis_client() -> aioredis.Redis:
    """Returns a client from the connection pool."""
    if _redis_pool is None:
        raise RuntimeError("Redis connection pool not initialized. Call init_redis first.")
    return aioredis.Redis(connection_pool=_redis_pool)

async def acquire_lock(lock_name: str, lease_time_sec: int = 10) -> bool:
    """Acquires a distributed lock using SETNX (SET if Not Exists) with an expiry."""
    client = get_redis_client()
    try:
        # px=lease_time_sec * 1000 sets expiration in milliseconds
        # nx=True ensures we only set it if it doesn't exist
        success = await client.set(f"lock:{lock_name}", "locked", ex=lease_time_sec, nx=True)
        status = "acquired" if success else "failed"
        REDIS_OPERATIONS.labels(operation="acquire_lock", status=status).inc()
        return bool(success)
    except Exception as e:
        REDIS_OPERATIONS.labels(operation="acquire_lock", status="error").inc()
        logger.error("redis_acquire_lock_failed", lock_name=lock_name, error=str(e))
        return False
    finally:
        await client.aclose()

async def release_lock(lock_name: str) -> None:
    """Releases the lock by deleting the key."""
    client = get_redis_client()
    try:
        await client.delete(f"lock:{lock_name}")
        REDIS_OPERATIONS.labels(operation="release_lock", status="success").inc()
    except Exception as e:
        REDIS_OPERATIONS.labels(operation="release_lock", status="error").inc()
        logger.error("redis_release_lock_failed", lock_name=lock_name, error=str(e))
    finally:
        await client.aclose()

async def cache_input_hash(input_hash: str, decision: str, expiry_sec: int = 3600) -> bool:
    """Caches the decision associated with an input hash for LLM bias memoization."""
    client = get_redis_client()
    try:
        success = await client.set(f"memo:{input_hash}", decision, ex=expiry_sec)
        REDIS_OPERATIONS.labels(operation="cache_input_hash", status="success").inc()
        return bool(success)
    except Exception as e:
        REDIS_OPERATIONS.labels(operation="cache_input_hash", status="error").inc()
        logger.error("redis_cache_input_hash_failed", input_hash=input_hash, error=str(e))
        return False
    finally:
        await client.aclose()

async def get_cached_decision(input_hash: str) -> Optional[str]:
    """Retrieves a cached decision for a given input hash, if it exists."""
    client = get_redis_client()
    try:
        res = await client.get(f"memo:{input_hash}")
        status = "hit" if res else "miss"
        REDIS_OPERATIONS.labels(operation="get_cached_decision", status=status).inc()
        return res
    except Exception as e:
        REDIS_OPERATIONS.labels(operation="get_cached_decision", status="error").inc()
        logger.error("redis_get_cached_decision_failed", input_hash=input_hash, error=str(e))
        return None
    finally:
        await client.aclose()
