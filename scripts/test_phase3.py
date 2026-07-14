import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from config.loader import load_config
from core.broker import KiteBroker
from core.state_persistence import SymbolState

class TestPhase3Broker(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = load_config()

    @patch("core.broker.get_redis_client")
    async def test_paper_trading_detection(self, mock_redis_client):
        """Test paper trading state toggle checking."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="true")
        mock_redis_client.return_value = mock_redis

        broker = KiteBroker()
        self.assertTrue(await broker.is_paper_trading())

        mock_redis.get = AsyncMock(return_value="false")
        self.assertFalse(await broker.is_paper_trading())

    @patch("core.db._db_client")
    @patch("core.broker.get_redis_client")
    async def test_place_paper_limit_order(self, mock_redis_client, mock_db):
        """Test placing an entry limit order in paper trading mode."""
        # 1. Mock redis to enforce paper trading mode
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="true")
        mock_redis_client.return_value = mock_redis

        # 2. Mock Supabase responses
        mock_execute = MagicMock()
        mock_execute.execute = AsyncMock(return_value=MagicMock(data=[]))
        
        mock_table = MagicMock()
        mock_table.insert = MagicMock(return_value=mock_execute)
        mock_table.upsert = MagicMock(return_value=mock_execute)
        mock_db.table = MagicMock(return_value=mock_table)

        broker = KiteBroker()
        order_id = await broker.place_entry_limit_order("TCS", "BUY", 10.0, 3200.0)
        
        self.assertTrue(order_id.startswith("paper-limit-"))
        mock_table.insert.assert_called_once()
        mock_table.upsert.assert_called_once()

    @patch("core.db._db_client")
    @patch("core.broker.get_redis_client")
    async def test_flatten_paper_symbol(self, mock_redis_client, mock_db):
        """Test closing a paper position via flattening."""
        # 1. Mock redis to enforce paper trading mode
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="true")
        mock_redis_client.return_value = mock_redis

        # 2. Mock Supabase responses
        mock_execute = MagicMock()
        mock_execute.execute = AsyncMock(return_value=MagicMock(data=[]))
        
        mock_eq = MagicMock()
        mock_eq.eq = MagicMock(return_value=mock_execute)
        
        mock_table = MagicMock()
        mock_table.update = MagicMock(return_value=mock_eq)
        mock_table.upsert = MagicMock(return_value=mock_execute)
        mock_db.table = MagicMock(return_value=mock_table)

        broker = KiteBroker()
        current_state = SymbolState(
            symbol="INFY",
            state="LONG",
            position_qty=20.0,
            avg_entry_price=1500.0,
            metadata={"trade_id": "mock-trade-id"}
        )
        
        success = await broker.flatten_symbol("INFY", current_state, "Test Exit")
        
        self.assertTrue(success)
        self.assertEqual(current_state.state, "FLAT")
        self.assertEqual(current_state.position_qty, 0.0)
        mock_table.update.assert_called_once()
        mock_table.upsert.assert_called_once()

if __name__ == "__main__":
    unittest.main()
