import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Import modules to verify correct syntax and packaging
from config.loader import load_config, get_config
from core.db import init_db, get_db
from core.redis_client import init_redis, acquire_lock, release_lock, cache_input_hash, get_cached_decision
from core.state_persistence import SymbolState, fetch_symbol_state, save_symbol_state, load_all_active_states
from executor import TradingExecutor

class TestPhase1(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Set dummy environments for loader tests
        os.environ["BOT_DATABASE_URL"] = "http://mock-supabase.co"
        os.environ["BOT_DATABASE_KEY"] = "mock-key"
        os.environ["BOT_REDIS_HOST"] = "localhost"
        os.environ["BOT_REDIS_PORT"] = "6379"

    def test_config_loader(self):
        """Test configuration loader and Pydantic validation."""
        config = load_config()
        self.assertEqual(config.database.url, "http://mock-supabase.co")
        self.assertEqual(config.database.key, "mock-key")
        self.assertEqual(config.redis.host, "localhost")
        self.assertEqual(config.redis.port, 6379)
        self.assertIn("RELIANCE", config.trading.symbols)
        self.assertEqual(config.risk.max_per_trade_risk_pct, 1.0)

    @patch("core.db._db_client")
    def test_symbol_state_pydantic(self, mock_db):
        """Test that the SymbolState model serializes and validates correctly."""
        now = datetime.now(timezone.utc)
        state = SymbolState(
            symbol="TCS",
            state="LONG",
            position_qty=100.0,
            avg_entry_price=3500.0,
            stop_loss_price=3465.0,
            take_profit_price=3600.0,
            last_tick_time=now,
            metadata={"source": "test"}
        )
        self.assertEqual(state.symbol, "TCS")
        self.assertEqual(state.state, "LONG")
        self.assertEqual(state.position_qty, 100.0)
        self.assertEqual(state.avg_entry_price, 3500.0)
        self.assertEqual(state.metadata["source"], "test")

    @patch("core.db._db_client")
    async def test_state_persistence_queries(self, mock_db):
        """Test Supabase select queries helper functions with mocks."""
        # Setup mock db responses
        mock_execute = MagicMock()
        mock_execute.execute = AsyncMock(return_value=MagicMock(data=[
            {
                "symbol": "INFY",
                "state": "MONITORING",
                "position_qty": 50.0,
                "avg_entry_price": 1400.0,
                "stop_loss_price": 1386.0,
                "take_profit_price": 1450.0,
                "last_tick_time": "2026-07-14T12:00:00Z",
                "metadata": {"test": True}
            }
        ]))
        
        mock_table = MagicMock()
        mock_table.select = MagicMock(return_value=MagicMock(neq=MagicMock(return_value=MagicMock(neq=MagicMock(return_value=mock_execute)))))
        mock_db.table = MagicMock(return_value=mock_table)

        # Run load active states asynchronously
        active_states = await load_all_active_states()
        
        self.assertIn("INFY", active_states)
        self.assertEqual(active_states["INFY"].state, "MONITORING")
        self.assertEqual(active_states["INFY"].position_qty, 50.0)

    @patch("executor.get_redis_client")
    async def test_paper_trading_modes(self, mock_redis_client):
        """Test paper trading active toggle detection."""
        # 1. Mock Redis returning None (falls back to config default: True)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis_client.return_value = mock_redis
        
        executor = TradingExecutor()
        is_paper = await executor.is_paper_trading()
        self.assertTrue(is_paper)
        
        # 2. Mock Redis returning 'false' (overrides default to false)
        mock_redis.get = AsyncMock(return_value="false")
        is_paper = await executor.is_paper_trading()
        self.assertFalse(is_paper)
        
        # 3. Mock Redis returning 'true' (explicitly true)
        mock_redis.get = AsyncMock(return_value="true")
        is_paper = await executor.is_paper_trading()
        self.assertTrue(is_paper)

if __name__ == "__main__":
    unittest.main()
