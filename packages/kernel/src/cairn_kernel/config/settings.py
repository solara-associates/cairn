from __future__ import annotations

import os
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class AppSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_name: str = "cairn"
    environment: Environment = Environment.DEV
    log_level: LogLevel = "INFO"

    @classmethod
    def from_env(cls, prefix: str = "CAIRN_") -> AppSettings:
        overrides = {
            key: value
            for key, value in os.environ.items()
            if key.startswith(prefix)
        }
        fields = {
            field: overrides[f"{prefix}{field.upper()}"]
            for field in cls.model_fields
            if f"{prefix}{field.upper()}" in overrides
        }
        return cls(**fields)
