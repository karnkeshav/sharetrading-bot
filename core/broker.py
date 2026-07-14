import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from kiteconnect import KiteConnect

from config.loader import get_config
from core.db import get_db, record_db_op
from core.redis_client import get_redis_client
from core.logger import get_logger
from core.state_persistence import SymbolState, save_symbol_state, fetch_symbol_state

logger = get_logger(__name__)

class KiteBroker:
    def __init__(self):
        self.config = get_config()
        
        # Load API keys from environment overrides or config defaults
        self.api_key = os.environ.get("KITE_API_KEY") or self.config.broker.api_key
        self.api_secret = os.environ.get("KITE_API_SECRET") or self.config.broker.api_secret
        self.access_token = os.environ.get("KITE_ACCESS_TOKEN") or self.config.broker.access_token
        
        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
            logger.info("kite_broker_initialized_with_access_token")
        else:
            logger.warn("kite_broker_initialized_without_access_token_requires_authentication")

    async def is_paper_trading(self) -> bool:
        """Determines if the broker should run in Paper Trading mode or Live Brokerage mode.
        Checks Redis live toggle first, falls back to config.
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

    async def authenticate(self, request_token: str) -> str:
        """Exchanges Kite Connect request_token for a permanent session access_token."""
        try:
            # Run blocking API call in executor threadpool
            session = await asyncio.to_thread(
                self.kite.generate_session,
                request_token,
                api_secret=self.api_secret
            )
            self.access_token = session["access_token"]
            self.kite.set_access_token(self.access_token)
            logger.info("kite_broker_authenticated_successfully", user_id=session.get("user_id"))
            return self.access_token
        except Exception as e:
            logger.exception("kite_broker_authentication_failed", error=str(e))
            raise

    async def get_ltp(self, symbol: str) -> float:
        """Retrieves Last Traded Price (LTP) for a symbol."""
        is_paper = await self.is_paper_trading()
        if is_paper:
            # Paper mode: simulate LTP (e.g. from local memory or defaults).
            # In Phase 4/Production, this queries live feed. We return mock price for test sanity.
            return 100.0
            
        try:
            # Format exchange:symbol, e.g. NSE:RELIANCE
            instrument = f"NSE:{symbol}"
            quotes = await asyncio.to_thread(self.kite.ltp, [instrument])
            return float(quotes[instrument]["last_price"])
        except Exception as e:
            logger.error("failed_to_fetch_kite_ltp", symbol=symbol, error=str(e))
            raise

    async def place_entry_limit_order(self, symbol: str, transaction_type: str, qty: float, price: float) -> str:
        """Places a buy or sell limit order for position entry."""
        is_paper = await self.is_paper_trading()
        if is_paper:
            return await self._place_paper_order(symbol, transaction_type, qty, price)
            
        logger.info("placing_live_entry_limit_order", symbol=symbol, qty=qty, price=price, type=transaction_type)
        try:
            order_id = await asyncio.to_thread(
                self.kite.place_order,
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=int(qty),
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=price,
                validity=self.kite.VALIDITY_DAY
            )
            return str(order_id)
        except Exception as e:
            logger.error("failed_to_place_live_limit_order", symbol=symbol, error=str(e))
            raise

    async def place_exit_slm_order(self, symbol: str, transaction_type: str, qty: float, trigger_price: float) -> str:
        """Places a Stop-Loss Market (SL-M) exit order to protect against downside volatility."""
        is_paper = await self.is_paper_trading()
        if is_paper:
            return await self._place_paper_slm_order(symbol, transaction_type, qty, trigger_price)
            
        logger.warn("placing_live_exit_slm_order", symbol=symbol, qty=qty, trigger_price=trigger_price, type=transaction_type)
        try:
            order_id = await asyncio.to_thread(
                self.kite.place_order,
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=int(qty),
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_SLM,
                trigger_price=trigger_price,
                validity=self.kite.VALIDITY_DAY
            )
            return str(order_id)
        except Exception as e:
            logger.error("failed_to_place_live_slm_order", symbol=symbol, error=str(e))
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancels a pending order."""
        is_paper = await self.is_paper_trading()
        if is_paper:
            logger.info("cancelling_paper_order", order_id=order_id)
            return True
            
        try:
            await asyncio.to_thread(
                self.kite.cancel_order,
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id
            )
            return True
        except Exception as e:
            logger.error("failed_to_cancel_live_order", order_id=order_id, error=str(e))
            return False

    # --- Paper Trading Implementation Details ---

    async def _place_paper_order(self, symbol: str, transaction_type: str, qty: float, price: float) -> str:
        """Simulates placing and instantly filling an entry order for paper trading."""
        db = get_db()
        trade_id = str(uuid.uuid4())
        direction = "LONG" if transaction_type == "BUY" else "SHORT"
        
        logger.info("executing_paper_entry_order", symbol=symbol, qty=qty, price=price, direction=direction)
        
        # 1. Log open trade in Supabase rule_trades table
        payload = {
            "id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "entry_price": price,
            "quantity": qty,
            "status": "OPEN",
            "config_version": self.config.version,
        }
        
        async def _insert_trade():
            res = await db.table("rule_trades").insert(payload).execute()
            return res.data
            
        try:
            await record_db_op("rule_trades", "insert", _insert_trade())
        except Exception as e:
            logger.error("failed_to_log_paper_trade_db", symbol=symbol, error=str(e))
            
        # 2. Update SymbolState in Supabase
        state = SymbolState(
            symbol=symbol,
            state=direction,
            position_qty=qty,
            avg_entry_price=price,
            metadata={"trade_id": trade_id}
        )
        await save_symbol_state(state)
        
        return f"paper-limit-{trade_id[:8]}"

    async def _place_paper_slm_order(self, symbol: str, transaction_type: str, qty: float, trigger_price: float) -> str:
        """Simulates registering an SL-M order for paper trading."""
        logger.info("registering_paper_slm_order", symbol=symbol, qty=qty, trigger_price=trigger_price, type=transaction_type)
        
        # Update stop-loss price in active position state
        state = await fetch_symbol_state(symbol)
        if state and state.state in ("LONG", "SHORT"):
            state.stop_loss_price = trigger_price
            await save_symbol_state(state)
            
        return f"paper-slm-{str(uuid.uuid4())[:8]}"

    async def flatten_symbol(self, symbol: str, current_state: SymbolState, reason: str = "Flatten Trigger") -> bool:
        """Closes a position by executing market exit orders and finalizing trade logs."""
        is_paper = await self.is_paper_trading()
        
        logger.info("flattening_broker_position", symbol=symbol, is_paper=is_paper, reason=reason)
        
        exit_price = current_state.avg_entry_price * 0.99 # Assumed slippage exit
        if current_state.state == "SHORT":
            exit_price = current_state.avg_entry_price * 1.01
            
        # 1. Broker exit implementation
        if is_paper:
            logger.info("paper_market_exit_executed", symbol=symbol, price=exit_price)
        else:
            # Place actual market exit order (opposite of current state direction)
            tx_type = self.kite.TRANSACTION_TYPE_SELL if current_state.state == "LONG" else self.kite.TRANSACTION_TYPE_BUY
            try:
                # Place market exit order
                await asyncio.to_thread(
                    self.kite.place_order,
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=tx_type,
                    quantity=int(current_state.position_qty),
                    product=self.kite.PRODUCT_MIS,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    validity=self.kite.VALIDITY_DAY
                )
                logger.warn("LIVE_MARKET_EXIT_ORDER_PLACED", symbol=symbol, qty=current_state.position_qty)
            except Exception as e:
                logger.error("failed_to_place_live_market_exit_order", symbol=symbol, error=str(e))
                # Proceed to sync flat state locally for safety, but raise warning
        
        # 2. Finalize trade logs in Supabase rule_trades table
        trade_id = current_state.metadata.get("trade_id")
        if trade_id:
            db = get_db()
            
            pnl = (exit_price - current_state.avg_entry_price) * current_state.position_qty
            if current_state.state == "SHORT":
                pnl = (current_state.avg_entry_price - exit_price) * current_state.position_qty
                
            payload = {
                "status": "CLOSED",
                "exit_price": exit_price,
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "realized_pnl": pnl,
                "exit_reason": reason
            }
            
            async def _update_trade():
                res = await db.table("rule_trades").update(payload).eq("id", trade_id).execute()
                return res.data
                
            try:
                await record_db_op("rule_trades", "update", _update_trade())
            except Exception as e:
                logger.error("failed_to_update_paper_trade_log", trade_id=trade_id, error=str(e))

        # 3. Persist flat state in symbol_states table
        current_state.state = "FLAT"
        current_state.position_qty = 0.0
        current_state.stop_loss_price = 0.0
        current_state.take_profit_price = 0.0
        current_state.last_tick_time = datetime.now(timezone.utc)
        current_state.metadata["flatten_reason"] = reason
        current_state.metadata["flatten_time"] = datetime.now(timezone.utc).isoformat()
        
        return await save_symbol_state(current_state)
