"""CAIRN cairn_adapters.provider_gcp.

R1-05: a read-only GCP inventory adapter. See ``adapter.py`` for the
``InventorySourcePort`` implementation and ``client.py`` for the GCP API
port, rate limiter and retry policy it runs every call through.

R1-11: a GCP billing import adapter. See ``billing.py`` for the
``BillingSourcePort`` implementation, which reads a GCP billing export
(a fixture file in tests) and canonicalizes it via ``cairn_modules.finops``.
"""

from cairn_adapters.provider_gcp.adapter import GcpInventoryAdapter
from cairn_adapters.provider_gcp.billing import (
    GcpBillingAdapter,
    GcpBillingExportSource,
    GcpBillingFileSource,
)
from cairn_adapters.provider_gcp.client import (
    GcpApiResponse,
    GcpHttpClient,
    RateLimiter,
    RetryConfig,
    call_with_retry,
)

__all__ = [
    "GcpApiResponse",
    "GcpBillingAdapter",
    "GcpBillingExportSource",
    "GcpBillingFileSource",
    "GcpHttpClient",
    "GcpInventoryAdapter",
    "RateLimiter",
    "RetryConfig",
    "call_with_retry",
]
