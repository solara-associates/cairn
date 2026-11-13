"""CAIRN cairn_modules.connections: R1-02 provider connection lifecycle."""

from cairn_modules.connections.models import (
    ConnectionScope,
    ConnectionStatus,
    ConnectionSummary,
    ProviderConnectionRecord,
    SecretDigest,
)
from cairn_modules.connections.ports import ProviderScopeValidator, ScopeCheckResult
from cairn_modules.connections.service import ConnectionRegistry

__all__ = [
    "ConnectionRegistry",
    "ConnectionScope",
    "ConnectionStatus",
    "ConnectionSummary",
    "ProviderConnectionRecord",
    "ProviderScopeValidator",
    "ScopeCheckResult",
    "SecretDigest",
]
