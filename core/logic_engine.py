import math
from typing import List, Tuple, Optional
from config.schema import AppConfig
from core.logger import get_logger

logger = get_logger(__name__)

def calculate_ema(data: List[float], period: int) -> List[float]:
    """Calculates the Exponential Moving Average (EMA) of a list of floats."""
    if not data or len(data) < period:
        return []
    
    ema = []
    # Initial SMA for the first period elements
    sma = sum(data[:period]) / period
    ema.append(sma)
    
    k = 2.0 / (period + 1.0)
    for value in data[period:]:
        next_ema = value * k + ema[-1] * (1.0 - k)
        ema.append(next_ema)
        
    # Pad the start with None equivalents (represented by index matching)
    # to maintain alignment with the original list size
    padding = [ema[0]] * (period - 1)
    return padding + ema

def calculate_tema(closes: List[float], period: int) -> Optional[float]:
    """Calculates the Triple Exponential Moving Average (TEMA) for a list of closes.
    Returns the latest TEMA value, or None if closes list is insufficient.
    """
    if len(closes) < (period * 3 - 2): # Minimum data required for 3 nested EMAs
        return None
        
    ema1 = calculate_ema(closes, period)
    if not ema1:
        return None
        
    ema2 = calculate_ema(ema1, period)
    if not ema2:
        return None
        
    ema3 = calculate_ema(ema2, period)
    if not ema3:
        return None
        
    # TEMA = 3*EMA1 - 3*EMA2 + EMA3
    return 3.0 * ema1[-1] - 3.0 * ema2[-1] + ema3[-1]

def calculate_linreg_slope(closes: List[float], period: int) -> Optional[float]:
    """Calculates the least-squares linear regression slope of the closes over the period."""
    n = len(closes)
    if n < period:
        return None
        
    # Use the latest 'period' elements
    y = closes[-period:]
    x = list(range(period))
    
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(val * val for val in x)
    sum_xy = sum(x_val * y_val for x_val, y_val in zip(x, y))
    
    denominator = period * sum_xx - sum_x * sum_x
    if denominator == 0:
        return 0.0
        
    slope = (period * sum_xy - sum_x * sum_y) / denominator
    return slope

def scan_universe(price: float, bid: float, ask: float, volume: float, avg_volume: float, atr: float, config: AppConfig) -> bool:
    """Evaluates whether a symbol passes liquidity, RVOL, and volatility filters."""
    if price <= 0 or bid <= 0 or ask <= 0 or avg_volume <= 0:
        return False
        
    # 1. Bid-ask spread
    spread_pct = (ask - bid) / bid
    if spread_pct > config.trading.universe_scan.min_spread_pct:
        logger.debug("scan_failed_spread", spread_pct=spread_pct, limit=config.trading.universe_scan.min_spread_pct)
        return False
        
    # 2. Relative Volume (RVOL)
    rvol = volume / avg_volume
    if rvol < config.trading.universe_scan.min_volume_rvol:
        logger.debug("scan_failed_rvol", rvol=rvol, limit=config.trading.universe_scan.min_volume_rvol)
        return False
        
    # 3. ATR Volatility
    atr_pct = (atr / price) * 100.0
    if atr_pct < config.trading.universe_scan.min_atr_pct:
        logger.debug("scan_failed_atr", atr_pct=atr_pct, limit=config.trading.universe_scan.min_atr_pct)
        return False
        
    return True

def calculate_composite_score(tema_val: float, price: float, linreg_slope: float, llm_bias: float, config: AppConfig) -> float:
    """Combines TEMA, Linear Regression slope, and LLM Bias into a composite score clamped between -1.0 and 1.0."""
    # 1. Normalize TEMA score: relative offset to TEMA. Scale so that 0.5% offset = 1.0 score
    tema_offset = (price - tema_val) / tema_val
    tema_score = max(-1.0, min(1.0, tema_offset / 0.005))
    
    # 2. Normalize LinReg slope: slope relative to price. Scale so that 0.05% slope per bar = 1.0 score
    slope_rel = linreg_slope / price
    slope_score = max(-1.0, min(1.0, slope_rel / 0.0005))
    
    # 3. LLM Bias (already clamped to [-1.0, 1.0] by design)
    llm_score = max(-1.0, min(1.0, llm_bias))
    
    # Composite score
    m = config.model
    composite = (m.weight_tema * tema_score) + (m.weight_linreg * slope_score) + (m.weight_llm * llm_score)
    return max(-1.0, min(1.0, composite))

def calculate_p_win(composite_score: float, config: AppConfig) -> float:
    """Calculates win probability using Platt scaling (Logistic Calibration)."""
    a = config.model.platt_a
    b = config.model.platt_b
    
    # P_win = 1 / (1 + exp(A * S_raw + B))
    try:
        power = a * composite_score + b
        # Bound power to prevent overflow
        power = max(-20.0, min(20.0, power))
        return 1.0 / (1.0 + math.exp(power))
    except Exception as e:
        logger.error("p_win_calculation_error", error=str(e))
        return 0.5

def evaluate_expectancy(p_win: float, entry_price: float, stop_loss: float, take_profit: float, is_long: bool, config: AppConfig) -> Tuple[bool, float]:
    """Applies pessimistic expectancy filter factoring in slippage, taxes, and brokerage.
    Returns (Proceed_Flag, Expected_PnL).
    """
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    
    if risk <= 0 or reward <= 0:
        return False, 0.0

    # Calculate pessimistic SRE costs (applied to both entry and exit legs)
    total_cost_pct = (config.model.brokerage_pct + config.model.slippage_pct + config.model.taxes_pct) / 100.0
    costs = (entry_price + (take_profit if p_win >= 0.5 else stop_loss)) * total_cost_pct
    
    # Expected Return = (P_win * Reward) - ((1 - P_win) * Risk) - Costs
    expected_pnl = (p_win * reward) - ((1.0 - p_win) * risk) - costs
    
    proceed = expected_pnl > 0
    return proceed, expected_pnl

def calculate_kelly_size(p_win: float, entry_price: float, stop_loss: float, take_profit: float, equity: float, config: AppConfig) -> float:
    """Calculates position sizing using fractional Kelly, strictly bounded by per-trade and exposure risk limits."""
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    
    if risk <= 0 or reward <= 0 or equity <= 0:
        return 0.0
        
    win_loss_ratio = reward / risk
    
    # Standard Kelly Formula: f* = P_win - (1 - P_win) / W
    kelly_f = p_win - ((1.0 - p_win) / win_loss_ratio)
    if kelly_f <= 0:
        return 0.0
        
    # Apply fractional Kelly multiplier
    fractional_kelly = kelly_f * config.risk.kelly_fraction
    
    # Max allocation (in currency) we can risk based on Kelly
    kelly_allocation = equity * fractional_kelly
    kelly_qty = kelly_allocation / risk
    
    # Limit 1: Max Risk per trade limit (e.g. 1% of total equity)
    max_risk_allowed = equity * (config.risk.max_per_trade_risk_pct / 100.0)
    qty_risk_limit = max_risk_allowed / risk
    
    # Limit 2: Max exposure limit (e.g. 20% of total equity value)
    max_exposure_allowed = equity * (config.risk.max_equity_exposure_pct / 100.0)
    qty_exposure_limit = max_exposure_allowed / entry_price
    
    # Final quantity is capped by all three constraints
    qty = min(kelly_qty, qty_risk_limit, qty_exposure_limit)
    return max(0.0, qty)
