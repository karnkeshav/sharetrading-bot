import asyncio
import argparse
import sys
import os
import time
from datetime import datetime, timezone
from typing import Dict

from config.loader import load_config, get_config
from core.db import init_db, get_db
from core.redis_client import init_redis, get_redis_client, acquire_lock, release_lock
from core.logger import setup_logger, get_logger
from core.metrics import (
    start_metrics_server,
    HEARTBEAT_TIMESTAMP,
    ACTIVE_POSITIONS,
    CYCLE_LATENCY,
    ERROR_COUNT,
    TICKS_PROCESSED
)
from core.state_persistence import (
    SymbolState,
    load_all_active_states,
    save_symbol_state
)
from core.broker import KiteBroker

logger = get_logger(__name__)

class TradingExecutor:
    def __init__(self):
        self.config = get_config()
        self.active_positions: Dict[str, SymbolState] = {}
        self.running = False
        self.loop_interval = 1.0 # Run cycle every 1.0 second
        self.heartbeat_file = "/tmp/trading_bot_heartbeat"
        self.last_paper_mode = None

    async def initialize(self):
        """Initializes databases, caches, and recovers state."""
        # Setup DB client
        await init_db(self.config.database.url, self.config.database.key)
        
        # Setup Redis client
        init_redis(
            host=self.config.redis.host,
            port=self.config.redis.port,
            db=self.config.redis.db,
            password=self.config.redis.password
        )
        
        # Setup Broker Client
        self.broker = KiteBroker()
        
        # Synchronize configuration metadata into the database
        await self.sync_config_version()

    async def sync_config_version(self):
        """Registers the current configuration version in the database if it doesn't exist."""
        db = get_db()
        version = self.config.version
        params = self.config.model_dump(exclude={"database", "redis"})
        
        logger.info("syncing_config_version", version=version)
        try:
            # Check if version exists
            res = await db.table("config_versions").select("*").eq("version", version).execute()
            if not res.data:
                # Insert configuration version
                await db.table("config_versions").insert({
                    "version": version,
                    "is_active": True, # For now, set this one active
                    "parameters": params
                }).execute()
                logger.info("config_version_registered", version=version)
            else:
                logger.info("config_version_already_registered", version=version)
        except Exception as e:
            logger.error("failed_to_sync_config_version", version=version, error=str(e))

    async def recover_state(self):
        """Pulls active positions from Supabase on startup/recovery."""
        logger.info("starting_crash_recovery")
        try:
            self.active_positions = await load_all_active_states()
            
            # Reset Prometheus active positions gauge
            for symbol in self.config.trading.symbols:
                ACTIVE_POSITIONS.labels(symbol=symbol).set(0)
            
            # Set active gauges for recovered positions
            for symbol, state in self.active_positions.items():
                ACTIVE_POSITIONS.labels(symbol=symbol).set(state.position_qty)
                
            logger.info("crash_recovery_completed", active_positions_count=len(self.active_positions))
        except Exception as e:
            ERROR_COUNT.labels(module="recovery", error_type=type(e).__name__).inc()
            logger.exception("crash_recovery_failed", error=str(e))
            raise

    async def write_heartbeat(self):
        """Updates the Prometheus gauge, local heartbeat file, and a Redis key."""
        now = time.time()
        HEARTBEAT_TIMESTAMP.set(now)
        
        # 1. Write to local file for Systemd/Docker health checks
        try:
            with open(self.heartbeat_file, "w") as f:
                f.write(str(int(now)))
        except Exception as e:
            logger.error("failed_to_write_heartbeat_file", error=str(e))

        # 2. Write to Redis
        redis = get_redis_client()
        try:
            await redis.set("heartbeat:executor", int(now), ex=30)
        except Exception as e:
            logger.error("failed_to_write_heartbeat_redis", error=str(e))
        finally:
            await redis.aclose()

    async def check_kill_switch(self) -> bool:
        """Checks if the global emergency kill-switch is active in Redis or Supabase."""
        redis = get_redis_client()
        try:
            kill_switch = await redis.get("kill_switch_active")
            if kill_switch and kill_switch == "true":
                logger.warn("kill_switch_detected_in_redis")
                return True
        except Exception as e:
            logger.error("failed_to_check_redis_kill_switch", error=str(e))
        finally:
            await redis.aclose()
            
        # Optional: check Supabase config versions or state flag if needed
        return False

    async def is_paper_trading(self) -> bool:
        """Determines if the bot is currently in Paper Trading mode.
        Checks Redis override first, falls back to static Pydantic config.
        """
        redis = get_redis_client()
        try:
            paper_active = await redis.get("paper_trading_active")
            if paper_active is not None:
                return paper_active.lower() == "true"
        except Exception as e:
            logger.error("failed_to_check_redis_paper_trading_flag", error=str(e))
        finally:
            await redis.aclose()
            
        return self.config.trading.paper_trading_active

    async def flatten_all(self, reason: str = "Emergency Kill-switch"):
        """Emergency flatten routine. Closes all active positions using market orders."""
        logger.warn("initiating_flatten_all", reason=reason, active_positions=list(self.active_positions.keys()))
        
        # Lock flattening process
        lock_acquired = await acquire_lock("flatten_all", lease_time_sec=30)
        if not lock_acquired:
            logger.error("failed_to_acquire_flatten_lock_already_running")
            return

        try:
            # Reload active states to make sure we don't miss any parallel writes
            self.active_positions = await load_all_active_states()
            
            if not self.active_positions:
                logger.info("no_active_positions_to_flatten")
                return

            for symbol, state in list(self.active_positions.items()):
                success = await self.broker.flatten_symbol(symbol, state, reason)
                if success:
                    self.active_positions.pop(symbol, None)
                    ACTIVE_POSITIONS.labels(symbol=symbol).set(0.0)
                else:
                    logger.error("failed_to_flatten_symbol_at_executor", symbol=symbol)
            
            logger.info("flatten_all_operation_completed")
        except Exception as e:
            ERROR_COUNT.labels(module="flatten", error_type=type(e).__name__).inc()
            logger.exception("error_during_flatten_all", error=str(e))
        finally:
            await release_lock("flatten_all")

    async def execute_cycle(self):
        """Runs a single deterministic Fast Loop iteration."""
        # 1. Update Watchdog / Heartbeat
        await self.write_heartbeat()
        
        # 2. Log mode transition if paper trading mode was toggled on the fly
        is_paper = await self.is_paper_trading()
        if self.last_paper_mode is None or self.last_paper_mode != is_paper:
            self.last_paper_mode = is_paper
            logger.info("trading_mode_status", paper_trading_active=is_paper, mode="PAPER" if is_paper else "LIVE")

        # 3. Check Emergency Kill-switch
        if await self.check_kill_switch():
            await self.flatten_all(reason="Kill-switch Active")
            self.running = False
            return

        # 3. Fast Loop Tick Processing & Monitor
        # For Phase 1 (Foundation & State), we scan the configured list of symbols,
        # update their state tick times, increment tick counters, and perform basic checks.
        for symbol in self.config.trading.symbols:
            TICKS_PROCESSED.labels(symbol=symbol).inc()
            
            # Basic state check: If we have an active position, monitor SL/TP guardrails
            if symbol in self.active_positions:
                state = self.active_positions[symbol]
                # Simulate monitoring active position
                state.last_tick_time = datetime.now(timezone.utc)
                # Simulate a save state periodically to prove persistence sync (e.g. metadata update)
                # In production, we'd only save on state transitions or SL/TP updates.
                # Here we just log a debug message.
                logger.debug("monitoring_active_position", symbol=symbol, state=state.state)

    async def start(self):
        """Starts the main execution loop."""
        self.running = True
        logger.info("executor_loop_starting", loop_interval=self.loop_interval)
        
        while self.running:
            start_time = time.perf_counter()
            try:
                await self.execute_cycle()
            except Exception as e:
                ERROR_COUNT.labels(module="loop", error_type=type(e).__name__).inc()
                logger.error("exception_in_execution_cycle", error=str(e))
            
            latency = time.perf_counter() - start_time
            CYCLE_LATENCY.observe(latency)
            
            # Maintain exact cycle timing
            sleep_time = max(0.0, self.loop_interval - latency)
            await asyncio.sleep(sleep_time)

        logger.info("executor_loop_stopped")

async def run_executor():
    """Startup wrapper for the execution process."""
    # Start Prometheus server
    start_metrics_server(port=int(os.environ.get("PROMETHEUS_PORT", 8000)))
    
    executor = TradingExecutor()
    await executor.initialize()
    await executor.recover_state()
    await executor.start()

async def run_flatten_cli():
    """Emergency manual override wrapper for CLI flatten execution."""
    executor = TradingExecutor()
    await executor.initialize()
    await executor.flatten_all(reason="CLI Manual Flatten Trigger")

if __name__ == "__main__":
    setup_logger(json_format=(os.environ.get("JSON_LOGS", "true").lower() == "true"))
    
    parser = argparse.ArgumentParser(description="Intraday Trading Bot - Executor Engine")
    parser.add_argument(
        "--flatten-all",
        action="store_true",
        help="Trigger emergency flattening of all active positions and exit"
    )
    args = parser.parse_args()

    if args.flatten_all or os.environ.get("FLATTEN_ALL") == "true":
        logger.info("manual_flatten_triggered_via_cli")
        asyncio.run(run_flatten_cli())
    else:
        try:
            asyncio.run(run_executor())
        except KeyboardInterrupt:
            logger.info("received_keyboard_interrupt_stopping")
        except Exception as e:
            logger.critical("unhandled_fatal_exception", error=str(e))
            sys.exit(1)
