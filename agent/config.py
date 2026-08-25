"""Centralized Environment & Application Configuration.

Loads configuration from environment variables and `.env` files with validation,
type safety, and clear fail-fast startup diagnostics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigurationError(ValueError):
    """Raised when application configuration is missing, invalid, or unreadable."""

    pass


def load_dotenv(dotenv_path: str | Path | None = None) -> dict[str, str]:
    """Parse a .env file and set values into os.environ if not already set.

    Does not overwrite existing environment variables.
    """
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    path = Path(dotenv_path)

    loaded: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return loaded

    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key:
                    os.environ.setdefault(key, val)
                    loaded[key] = val
    except Exception as e:
        raise ConfigurationError(f"Failed to read environment file at '{path}': {e}") from e

    return loaded


class AppConfig(BaseModel):
    """Immutable application settings validated at startup."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    environment: Literal["development", "staging", "production", "test"] = "development"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = Field(default=8000, ge=1, le=65535)
    database_path: str = "data/dev.db"
    rules_path: str = "agent/policy/rules.yaml"
    diagnosis_provider: Literal["stub", "baseline", "groq", "claude"] = "stub"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Provider & Gateway API Keys (Optional unless the corresponding provider is selected)
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    # Overrides
    holdout_fraction: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("rules_path")
    @classmethod
    def validate_rules_file(cls, v: str) -> str:
        # Check if the rules path exists or can be resolved relative to repo root
        path = Path(v)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parent.parent
            path = repo_root / v
        if not path.exists():
            raise ConfigurationError(f"Configured rules file does not exist: '{v}' (resolved to '{path}')")
        return v


def load_config(
    dotenv_path: str | Path | None = None,
    *,
    require_provider_keys: bool = False,
    require_razorpay_keys: bool = False,
) -> AppConfig:
    """Load and validate application configuration from environment and .env file.

    Parameters
    ----------
    dotenv_path:
        Optional path to .env file. Defaults to repo root `.env`.
    require_provider_keys:
        If True, validates that API keys for the configured `diagnosis_provider` are present.
    require_razorpay_keys:
        If True, validates that Razorpay test/live keys are present.

    Returns
    -------
    AppConfig
        Validated, immutable application settings.

    Raises
    ------
    ConfigurationError
        If required environment variables or files are missing or invalid.
    """
    load_dotenv(dotenv_path)

    # Resolve port safely
    port_raw = os.environ.get("DASHBOARD_PORT", os.environ.get("PORT", "8000"))
    try:
        port = int(port_raw)
    except ValueError:
        raise ConfigurationError(f"Invalid DASHBOARD_PORT: '{port_raw}' is not an integer")

    # Resolve holdout fraction if set
    holdout_raw = os.environ.get("HOLDOUT_FRACTION")
    holdout_frac: float | None = None
    if holdout_raw:
        try:
            holdout_frac = float(holdout_raw)
            if not 0.0 <= holdout_frac <= 1.0:
                raise ValueError
        except ValueError:
            raise ConfigurationError(f"Invalid HOLDOUT_FRACTION: '{holdout_raw}' must be a float between 0.0 and 1.0")

    config_data: dict[str, Any] = {
        "environment": os.environ.get("ENVIRONMENT", os.environ.get("ENV", "development")),
        "dashboard_host": os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        "dashboard_port": port,
        "database_path": os.environ.get("DATABASE_PATH", "data/dev.db"),
        "rules_path": os.environ.get("RULES_PATH", "agent/policy/rules.yaml"),
        "diagnosis_provider": os.environ.get("DIAGNOSIS_PROVIDER", "stub").lower(),
        "log_level": os.environ.get("LOG_LEVEL", "INFO").upper(),
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY") or None,
        "groq_api_key": os.environ.get("GROQ_API_KEY") or None,
        "razorpay_key_id": os.environ.get("RAZORPAY_KEY_ID") or None,
        "razorpay_key_secret": os.environ.get("RAZORPAY_KEY_SECRET") or None,
        "holdout_fraction": holdout_frac,
    }

    try:
        config = AppConfig(**config_data)
    except Exception as e:
        raise ConfigurationError(f"Configuration validation failed: {e}") from e

    # Provider specific validation
    if require_provider_keys:
        if config.diagnosis_provider == "claude" and not config.anthropic_api_key:
            raise ConfigurationError(
                "Missing required environment variable 'ANTHROPIC_API_KEY' for diagnosis provider 'claude'. "
                "Please set ANTHROPIC_API_KEY in your .env file or environment."
            )
        if config.diagnosis_provider == "groq" and not config.groq_api_key:
            raise ConfigurationError(
                "Missing required environment variable 'GROQ_API_KEY' for diagnosis provider 'groq'. "
                "Please set GROQ_API_KEY in your .env file or environment."
            )

    if require_razorpay_keys:
        if not config.razorpay_key_id or not config.razorpay_key_secret:
            raise ConfigurationError(
                "Missing required Razorpay credentials ('RAZORPAY_KEY_ID' and 'RAZORPAY_KEY_SECRET'). "
                "Please set them in your .env file or environment."
            )

    return config
