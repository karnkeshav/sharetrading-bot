from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from core.db import get_db, record_db_op
from core.logger import get_logger

logger = get_logger(__name__)

class SymbolState(BaseModel):
    symbol: str
    state: str = Field("IDLE", description="IDLE, MONITORING, LONG, SHORT, FLAT")
    position_qty: float = Field(0.0)
    avg_entry_price: float = Field(0.0)
    stop_loss_price: float = Field(0.0)
    take_profit_price: float = Field(0.0)
    last_tick_time: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

async def fetch_symbol_state(symbol: str) -> Optional[SymbolState]:
    """Retrieves the state of a single symbol from Supabase."""
    db = get_db()
    
    async def _fetch():
        res = await db.table("symbol_states").select("*").eq("symbol", symbol).execute()
        return res.data

    try:
        data = await record_db_op("symbol_states", "select", _fetch())
        if not data:
            return None
        
        row = data[0]
        # Parse datetime if exists
        last_tick_time = None
        if row.get("last_tick_time"):
            last_tick_time = datetime.fromisoformat(row["last_tick_time"].replace("Z", "+00:00"))
            
        return SymbolState(
            symbol=row["symbol"],
            state=row["state"],
            position_qty=float(row["position_qty"]),
            avg_entry_price=float(row["avg_entry_price"]),
            stop_loss_price=float(row["stop_loss_price"]),
            take_profit_price=float(row["take_profit_price"]),
            last_tick_time=last_tick_time,
            metadata=row.get("metadata", {})
        )
    except Exception as e:
        logger.error("failed_to_fetch_symbol_state", symbol=symbol, error=str(e))
        return None

async def save_symbol_state(state: SymbolState) -> bool:
    """Saves or updates the symbol state in the Supabase database (Upsert)."""
    db = get_db()
    
    payload = {
        "symbol": state.symbol,
        "state": state.state,
        "position_qty": state.position_qty,
        "avg_entry_price": state.avg_entry_price,
        "stop_loss_price": state.stop_loss_price,
        "take_profit_price": state.take_profit_price,
        "last_tick_time": state.last_tick_time.isoformat() if state.last_tick_time else None,
        "metadata": state.metadata,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    async def _upsert():
        res = await db.table("symbol_states").upsert(payload).execute()
        return res.data

    try:
        await record_db_op("symbol_states", "upsert", _upsert())
        logger.debug("symbol_state_saved", symbol=state.symbol, state=state.state)
        return True
    except Exception as e:
        logger.error("failed_to_save_symbol_state", symbol=state.symbol, error=str(e))
        return False

async def load_all_active_states() -> Dict[str, SymbolState]:
    """Retrieves all symbol states where state is not IDLE or FLAT (for active position recovery)."""
    db = get_db()
    
    async def _fetch_active():
        # Retrieve all states. Filter out IDLE and FLAT at application level or via multiple in query
        res = await db.table("symbol_states").select("*").neq("state", "IDLE").neq("state", "FLAT").execute()
        return res.data

    active_states = {}
    try:
        data = await record_db_op("symbol_states", "select_active", _fetch_active())
        for row in data:
            last_tick_time = None
            if row.get("last_tick_time"):
                last_tick_time = datetime.fromisoformat(row["last_tick_time"].replace("Z", "+00:00"))
                
            state_obj = SymbolState(
                symbol=row["symbol"],
                state=row["state"],
                position_qty=float(row["position_qty"]),
                avg_entry_price=float(row["avg_entry_price"]),
                stop_loss_price=float(row["stop_loss_price"]),
                take_profit_price=float(row["take_profit_price"]),
                last_tick_time=last_tick_time,
                metadata=row.get("metadata", {})
            )
            active_states[state_obj.symbol] = state_obj
            
        logger.info("active_states_recovered", count=len(active_states), symbols=list(active_states.keys()))
        return active_states
    except Exception as e:
        logger.error("failed_to_load_active_states", error=str(e))
        return {}
