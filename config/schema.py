from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class DatabaseConfig(BaseModel):
    url: str = Field(..., description="Supabase / PostgreSQL connection URL")
    key: Optional[str] = Field(None, description="Supabase API key (if using Supabase client)")
    pool_size: int = Field(5, description="Connection pool size")

class RedisConfig(BaseModel):
    host: str = Field("localhost", description="Redis host")
    port: int = Field(6379, description="Redis port")
    db: int = Field(0, description="Redis database index")
    password: Optional[str] = Field(None, description="Redis password")

class RiskConfig(BaseModel):
    max_daily_loss_pct: float = Field(5.0, description="Kill-switch daily loss limit in percentage")
    max_per_trade_risk_pct: float = Field(1.0, description="Risk budget per trade (e.g. 1% of equity)")
    kelly_fraction: float = Field(0.5, description="Fraction of Kelly size to use")
    max_equity_exposure_pct: float = Field(20.0, description="Maximum total exposure as a percentage of total equity")

class UniverseScanConfig(BaseModel):
    min_spread_pct: float = Field(0.01, description="Minimum bid-ask spread percentage")
    min_volume_rvol: float = Field(1.5, description="Minimum relative volume multiplier")
    min_atr_pct: float = Field(0.5, description="Minimum Average True Range as percentage of price")

class TradingConfig(BaseModel):
    symbols: List[str] = Field(..., description="List of tradeable symbols")
    universe_scan: UniverseScanConfig
    signal_persistence_ticks: int = Field(3, description="Number of ticks/bar close to verify signal persistence")
    paper_trading_active: bool = Field(True, description="Toggle between live paper trading and real brokerage trading")

class AppConfig(BaseModel):
    version: str = Field("v1.0", description="Configuration version string")
    database: DatabaseConfig
    redis: RedisConfig
    risk: RiskConfig
    trading: TradingConfig
    extra: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary extra params for ensemble model")
