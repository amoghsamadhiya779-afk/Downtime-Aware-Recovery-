"""Configuration and Startup Validation Test Suite.

Verifies that:
1. Environment variables and .env files are loaded properly.
2. Hardcoded secrets are not required in development/test.
3. Startup fails fast with clear ConfigurationError when required configuration is missing or invalid.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from agent.config import AppConfig, ConfigurationError, load_config, load_dotenv


def test_load_dotenv_parsing(tmp_path):
    env_file = tmp_path / ".env.test"
    env_file.write_text(
        """
        # Test environment file
        TEST_VAR_A=alpha
        TEST_VAR_B='beta_quoted'
        TEST_VAR_C="gamma_double_quoted"
        
        INVALID_LINE_WITHOUT_EQUALS
        # COMMENT_LINE=ignored
        """,
        encoding="utf-8",
    )

    loaded = load_dotenv(env_file)
    assert loaded.get("TEST_VAR_A") == "alpha"
    assert loaded.get("TEST_VAR_B") == "beta_quoted"
    assert loaded.get("TEST_VAR_C") == "gamma_double_quoted"
    assert "COMMENT_LINE" not in loaded


def test_load_config_defaults(monkeypatch):
    # Clear environment variables to verify clean defaults
    for key in ["ENVIRONMENT", "DASHBOARD_PORT", "DATABASE_PATH", "DIAGNOSIS_PROVIDER", "LOG_LEVEL"]:
        monkeypatch.delenv(key, raising=False)

    config = load_config(dotenv_path=Path("non_existent_env_file"))
    assert config.environment == "development"
    assert config.dashboard_host == "127.0.0.1"
    assert config.dashboard_port == 8000
    assert config.diagnosis_provider == "stub"
    assert config.log_level == "INFO"


def test_load_config_custom_env_overrides(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("DASHBOARD_PORT", "9090")
    monkeypatch.setenv("DATABASE_PATH", "data/custom.db")
    monkeypatch.setenv("DIAGNOSIS_PROVIDER", "baseline")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("HOLDOUT_FRACTION", "0.35")

    config = load_config(dotenv_path=Path("non_existent_env_file"))
    assert config.environment == "staging"
    assert config.dashboard_host == "0.0.0.0"
    assert config.dashboard_port == 9090
    assert config.database_path == "data/custom.db"
    assert config.diagnosis_provider == "baseline"
    assert config.log_level == "DEBUG"
    assert config.holdout_fraction == 0.35


def test_startup_fails_on_invalid_port(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "not_a_number")
    with pytest.raises(ConfigurationError, match="Invalid DASHBOARD_PORT"):
        load_config(dotenv_path=Path("non_existent_env_file"))

    monkeypatch.setenv("DASHBOARD_PORT", "99999")
    with pytest.raises(ConfigurationError, match="Configuration validation failed"):
        load_config(dotenv_path=Path("non_existent_env_file"))


def test_startup_fails_on_invalid_holdout_fraction(monkeypatch):
    monkeypatch.setenv("HOLDOUT_FRACTION", "1.5")
    with pytest.raises(ConfigurationError, match="Invalid HOLDOUT_FRACTION"):
        load_config(dotenv_path=Path("non_existent_env_file"))


def test_startup_fails_on_missing_rules_file(monkeypatch):
    monkeypatch.setenv("RULES_PATH", "non_existent_rules.yaml")
    with pytest.raises(ConfigurationError, match="Configured rules file does not exist"):
        load_config(dotenv_path=Path("non_existent_env_file"))


def test_startup_fails_on_missing_provider_api_key(monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="Missing required environment variable 'ANTHROPIC_API_KEY'"):
        load_config(dotenv_path=Path("non_existent_env_file"), require_provider_keys=True)

    monkeypatch.setenv("DIAGNOSIS_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="Missing required environment variable 'GROQ_API_KEY'"):
        load_config(dotenv_path=Path("non_existent_env_file"), require_provider_keys=True)


def test_startup_fails_on_missing_razorpay_keys(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    with pytest.raises(ConfigurationError, match="Missing required Razorpay credentials"):
        load_config(dotenv_path=Path("non_existent_env_file"), require_razorpay_keys=True)
