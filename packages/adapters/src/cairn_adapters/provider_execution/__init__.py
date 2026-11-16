"""R4-02a: ``ProviderExecutionPort`` contract and credential-scoping
abstraction (ADR-010, spec §5.4). Provider-agnostic; see
``cairn_adapters.execution_gcp`` for the first (GCP) adapter skeleton.
"""

from cairn_adapters.provider_execution.fake import (
    FAKE_ADAPTER_KIND,
    FAKE_PROVIDER,
    FakeProviderExecutionAdapter,
)
from cairn_adapters.provider_execution.ports import (
    ApplyRequest,
    ApplyResult,
    ExecutionScope,
    PlanRequest,
    PlanResult,
    ProviderExecutionDescriptor,
    ProviderExecutionPort,
    RollbackRequest,
    RollbackResult,
)
from cairn_adapters.provider_execution.token import (
    DEFAULT_TOKEN_TTL_SECONDS,
    MAX_TOKEN_TTL_SECONDS,
    FakeTokenProvider,
    ScopedToken,
    TokenProvider,
    TokenRequest,
)

__all__ = [
    "DEFAULT_TOKEN_TTL_SECONDS",
    "FAKE_ADAPTER_KIND",
    "FAKE_PROVIDER",
    "MAX_TOKEN_TTL_SECONDS",
    "ApplyRequest",
    "ApplyResult",
    "ExecutionScope",
    "FakeProviderExecutionAdapter",
    "FakeTokenProvider",
    "PlanRequest",
    "PlanResult",
    "ProviderExecutionDescriptor",
    "ProviderExecutionPort",
    "RollbackRequest",
    "RollbackResult",
    "ScopedToken",
    "TokenProvider",
    "TokenRequest",
]
