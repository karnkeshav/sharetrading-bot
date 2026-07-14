import os
import yaml
from pathlib import Path
from typing import Optional
from config.schema import AppConfig

_config: Optional[AppConfig] = None

def load_config(config_path: Optional[str] = None) -> AppConfig:
    global _config
    if _config is not None:
        return _config

    if config_path is None:
        # Default to settings.yaml in the same directory structure
        config_path = os.environ.get("BOT_CONFIG_PATH", str(Path(__file__).parent / "settings.yaml"))

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at {path}")

    with open(path, "r") as f:
        config_dict = yaml.safe_load(f)

    # Apply environment variable overrides for database config
    if "database" not in config_dict:
        config_dict["database"] = {}
    
    db_url = os.environ.get("BOT_DATABASE_URL") or os.environ.get("SUPABASE_URL")
    if db_url:
        config_dict["database"]["url"] = db_url
    
    db_key = os.environ.get("BOT_DATABASE_KEY") or os.environ.get("SUPABASE_KEY")
    if db_key:
        config_dict["database"]["key"] = db_key

    # Apply environment variable overrides for redis config
    if "redis" not in config_dict:
        config_dict["redis"] = {}
        
    redis_host = os.environ.get("BOT_REDIS_HOST") or os.environ.get("REDIS_HOST")
    if redis_host:
        config_dict["redis"]["host"] = redis_host
        
    redis_port = os.environ.get("BOT_REDIS_PORT") or os.environ.get("REDIS_PORT")
    if redis_port:
        config_dict["redis"]["port"] = int(redis_port)
        
    redis_pass = os.environ.get("BOT_REDIS_PASSWORD") or os.environ.get("REDIS_PASSWORD")
    if redis_pass:
        config_dict["redis"]["password"] = redis_pass

    # Version override
    version_env = os.environ.get("BOT_CONFIG_VERSION")
    if version_env:
        config_dict["version"] = version_env

    # Validate configuration
    _config = AppConfig(**config_dict)
    return _config

def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config
