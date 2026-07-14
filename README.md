# Intraday Trading Bot (Project: Sharetrading-bot)

An SRE-led, asynchronous, multi-track ensemble automated intraday trading bot built with Python 3.14.

This repository contains **Phase 1: Foundation & State** implementation.

## Project Structure

```text
sharetrading-bot/
├── config/
│   ├── loader.py            # Config validation and environment-variable loader
│   ├── schema.py            # Pydantic v2 configuration schema
│   └── settings.yaml        # Default configuration values
├── core/
│   ├── db.py                # Supabase async postgres database client wrapper
│   ├── logger.py            # Structured JSON logger (Grafana Loki compatible)
│   ├── metrics.py           # Prometheus metrics definitions and scrape server
│   ├── redis_client.py      # Redis wrapper for atomic locks and input memoization
│   └── state_persistence.py # SymbolState structure, startup recovery, and sync
├── scripts/
│   ├── schema.sql           # Database tables script for Supabase / PostgreSQL
│   └── test_phase1.py       # Async unit testing script
├── Dockerfile               # Production container definition
├── docker-compose.yml       # Orchestrates App, Redis, Prometheus, and Grafana
├── executor.py              # Async Fast Loop executor, Heartbeat Watchdog, & CLI flatten overrides
├── prometheus.yml           # Prometheus scraping rules
└── requirements.txt         # Core dependencies
```

## Features Implemented in Phase 1

1.  **State Persistence & Crash Recovery:**
    *   `state_persistence.py` automatically synchronizes current trade positions and state configurations (`SymbolState`) to/from Supabase.
    *   During crash recovery on startup, `executor.py` loads any active positions where state is not `IDLE` or `FLAT` to resume live tracking.
2.  **Atomic State Locking & Caching:**
    *   Distributed locks are managed in Redis via `acquire_lock` and `release_lock` (preventing double entries or race conditions).
    *   Decision/sentiment input-hash memoization is ready to prevent repetitive LLM sentiment queries.
3.  **Observability & Telemetry:**
    *   Structured JSON logger setup using `structlog` (directly consumable by Grafana Loki).
    *   Custom Prometheus metrics exporter (on port `8000`) tracking heartbeat epoch timestamps, ticks processed, database operation status, active position sizes, daily risk usage, and cycle loop latencies.
4.  **Deterministic Fast Loop & Watchdog:**
    *   `executor.py` runs an async loop containing a Heartbeat Watchdog that periodically writes status markers to Redis and the local host filesystem `/tmp/trading_bot_heartbeat`.
5.  **Emergency Shutoff (Kill-switch / `FLATTEN_ALL`):**
    *   The bot monitors a Redis kill-switch flag `kill_switch_active` in its execution cycle. If set to `"true"`, it flattens all active positions immediately using simulated market orders.
    *   Manual overrides can be performed directly via the command-line command:
        ```bash
        python executor.py --flatten-all
        ```

---

## Getting Started

### 1. Requirements

Ensure Python 3.14.x is installed. Install all Python package dependencies:

```bash
pip install -r requirements.txt
```

### 2. Run Local Unit Tests

Verify everything compiles and functions properly under local mocking:

```bash
python -m unittest scripts/test_phase1.py
```

### 3. Run via Docker Compose

To start the complete environment (Trading Bot, Redis, Prometheus, Grafana):

```bash
# Setup Supabase credentials or let it fall back to the mock defaults
export SUPABASE_URL="https://your-supabase-project.supabase.co"
export SUPABASE_KEY="your-supabase-service-role-key"

docker-compose up --build -d
```

Metrics will be exposed at:
- **Prometheus:** `http://localhost:9090`
- **Grafana:** `http://localhost:3000` (Default credentials: `admin` / `admin`)