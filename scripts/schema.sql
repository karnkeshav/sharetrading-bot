-- PostgreSQL / Supabase Schema for Intraday Trading Bot

-- Enable UUID extension if not already present
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Configuration Versions
CREATE TABLE IF NOT EXISTS config_versions (
    version VARCHAR(50) PRIMARY KEY,
    is_active BOOLEAN DEFAULT FALSE,
    parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure only one configuration version is active at any time
CREATE UNIQUE INDEX IF NOT EXISTS config_versions_active_idx ON config_versions (is_active) WHERE is_active = TRUE;

-- 2. Symbol States (for active positions & crash recovery)
CREATE TABLE IF NOT EXISTS symbol_states (
    symbol VARCHAR(50) PRIMARY KEY,
    state VARCHAR(50) NOT NULL, -- IDLE, MONITORING, LONG, SHORT, FLAT
    position_qty NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC NOT NULL DEFAULT 0,
    stop_loss_price NUMERIC NOT NULL DEFAULT 0,
    take_profit_price NUMERIC NOT NULL DEFAULT 0,
    last_tick_time TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for searching non-idle states (which need monitoring/exiting)
CREATE INDEX IF NOT EXISTS symbol_states_active_idx ON symbol_states (state) WHERE state != 'IDLE';

-- 3. Signals Log (Slow Loop Input)
CREATE TABLE IF NOT EXISTS signals_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(50) NOT NULL,
    tema_score NUMERIC,
    linreg_score NUMERIC,
    llm_sentiment_score NUMERIC,
    composite_score NUMERIC,
    p_win NUMERIC,
    expected_return NUMERIC,
    decision VARCHAR(50) NOT NULL, -- BUY, SELL, HOLD, NO_TRADE
    config_version VARCHAR(50) REFERENCES config_versions(version),
    input_hash VARCHAR(64) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS signals_log_timestamp_idx ON signals_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS signals_log_symbol_idx ON signals_log (symbol);

-- 4. Rule Trades (Trade History)
CREATE TABLE IF NOT EXISTS rule_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL, -- LONG, SHORT
    entry_time TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC NOT NULL,
    exit_time TIMESTAMPTZ,
    exit_price NUMERIC,
    quantity NUMERIC NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN', -- OPEN, CLOSED, CANCELLED
    realized_pnl NUMERIC DEFAULT 0,
    exit_reason VARCHAR(50), -- SL, TP, FLATTEN, TIME_EXIT
    config_version VARCHAR(50) REFERENCES config_versions(version),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rule_trades_symbol_idx ON rule_trades (symbol);
CREATE INDEX IF NOT EXISTS rule_trades_status_idx ON rule_trades (status);
CREATE INDEX IF NOT EXISTS rule_trades_created_at_idx ON rule_trades (created_at DESC);
