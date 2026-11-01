"""Agentic Trader — settings via env + YAML."""
from __future__ import annotations
import os, json, pathlib
from ruamel.yaml import YAML
from pydantic_settings import BaseSettings
from pydantic import BaseModel

def _find_config_dir() -> pathlib.Path:
    """Search upward from this file for a 'config' directory."""
    p = pathlib.Path(__file__).resolve()
    for parent in p.parents:
        candidate = parent / "config"
        if candidate.is_dir() and (candidate / "universe.yaml").exists():
            return candidate
    return pathlib.Path(__file__).parent.parent.parent.parent.parent / "config"

_CONFIG_DIR = _find_config_dir()
_yaml = YAML(typ="safe")

_REPO_ROOT = _CONFIG_DIR.parent

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./trader.db"
    # Neon's direct (non -pooler) URL; used for DDL, since PgBouncer transaction mode is for app traffic
    DATABASE_URL_UNPOOLED: str = ""
    SESSION_SECRET: str = "dev-secret-change-me"
    WEB_ORIGIN: str = "http://localhost:3000"
    ALPACA_API_KEY_ID: str = ""
    ALPACA_API_SECRET_KEY: str = ""
    ALPACA_PAPER: bool = True
    EXPECTED_PAPER_ACCOUNT: str = ""
    GEMINI_API_KEY: str = ""
    AGENT_ENABLED: bool = True
    TRADING_FROZEN: bool = False
    NEXT_PUBLIC_API_URL: str = "http://localhost:8000"
    ADMIN_TOKEN: str = ""
    APPROVER_ADDRESSES: str = ""

    class Config:
        # `neon env pull` writes the repo-root .env.local; later files win, real env vars beat all of them
        env_file = (_REPO_ROOT / ".env", _REPO_ROOT / ".env.local", ".env")
        extra = "ignore"

settings = Settings()

def env(name: str) -> str:
    """A setting that may change at runtime: the live env var, else the value from .env / .env.local.
    os.environ alone misses the env files, which pydantic loads into `settings` only."""
    return os.environ.get(name, getattr(settings, name))

def load_yaml(name: str) -> dict:
    with open(_CONFIG_DIR / name) as f:
        return _yaml.load(f) or {}

def save_yaml(name: str, data: dict):
    with open(_CONFIG_DIR / name, "w") as f:
        _yaml.dump(data, f)

def get_universe() -> dict:
    return load_yaml("universe.yaml")

def get_strategy() -> dict:
    return load_yaml("strategy.yaml")

def get_risk() -> dict:
    return load_yaml("risk.yaml")

def get_shockmap() -> dict:
    return load_yaml("shockmap.yaml")

def get_approvers() -> dict:
    """approvers.yaml plus any comma-separated APPROVER_ADDRESSES (survives redeploys, unlike YAML edits)."""
    cfg = load_yaml("approvers.yaml")
    cfg["approvers"] = list(cfg.get("approvers") or [])
    known = {a["address"].lower() for a in cfg["approvers"]}
    for addr in filter(None, (a.strip() for a in env("APPROVER_ADDRESSES").split(","))):
        if addr.lower() not in known:
            cfg["approvers"].append({"name": "env", "address": addr, "roles": ["operator"]})
    return cfg
