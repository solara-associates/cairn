"""R4-02a: the GCP ``ProviderExecutionPort`` adapter skeleton (ADR-010,
spec §5.4) -- structure only, no cloud. See
``cairn_adapters.execution_gcp.adapter`` for why this adapter is not yet
reachable through ``cairn_kernel.execution_gate.gate.ExecutionGate``.
"""

from cairn_adapters.execution_gcp.adapter import (
    ADAPTER_KIND,
    PROVIDER,
    GcpProviderExecutionAdapter,
)
from cairn_adapters.execution_gcp.client import GcpExecutionClient, GcpExecutionResponse

__all__ = [
    "ADAPTER_KIND",
    "PROVIDER",
    "GcpExecutionClient",
    "GcpExecutionResponse",
    "GcpProviderExecutionAdapter",
]
