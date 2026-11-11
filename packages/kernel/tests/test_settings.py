import pytest
from cairn_kernel.config import AppSettings, Environment
from pydantic import ValidationError as PydanticValidationError


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAIRN_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CAIRN_LOG_LEVEL", raising=False)
    settings = AppSettings()
    assert settings.service_name == "cairn"
    assert settings.environment is Environment.DEV
    assert settings.log_level == "INFO"


def test_from_env_reads_prefixed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAIRN_ENVIRONMENT", "staging")
    monkeypatch.setenv("CAIRN_LOG_LEVEL", "DEBUG")
    settings = AppSettings.from_env()
    assert settings.environment is Environment.STAGING
    assert settings.log_level == "DEBUG"


def test_from_env_ignores_unrelated_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAIRN_ENVIRONMENT", "prod")
    monkeypatch.setenv("UNRELATED_ENVIRONMENT", "prod")
    monkeypatch.setenv("OTHER_FLAG", "1")
    settings = AppSettings.from_env()
    assert settings.environment is Environment.PROD


def test_settings_are_frozen() -> None:
    settings = AppSettings()
    with pytest.raises(PydanticValidationError):
        settings.environment = Environment.PROD


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        AppSettings(environment="not-a-real-environment")
    with pytest.raises(PydanticValidationError):
        AppSettings(log_level="TRACE")
