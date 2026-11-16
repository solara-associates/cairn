"""R4-02a: the GCP execution HTTP port -- the write/apply-side mirror of
R1-05's read-only ``cairn_adapters.provider_gcp.client.GcpHttpClient``.

Nothing here imports a GCP SDK, ``requests``, ``httpx``, or anything else
that could make a real network call -- ``GcpExecutionClient`` is a
``Protocol`` so a fake implementation can satisfy it in tests
(``packages/adapters/tests/test_execution_gcp_adapter.py``). No concrete
implementation of this protocol exists in this unit; building one against
a real GCP API is explicitly out of scope here (that is the cloud-gated
units 785/786's job, once §2.6's IAM setup exists), and this module's own
no-SDK-import test would fail the moment one is added without also moving
it behind the same construction-proof convention
``cairn_adapters.provider_core``'s contract test already uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GcpExecutionResponse:
    """The shape every ``GcpExecutionClient`` call returns."""

    status_code: int
    body: Mapping[str, object]


class GcpExecutionClient(Protocol):
    """The outbound port ``GcpProviderExecutionAdapter`` calls through.

    Both verbs take the short-lived ``token`` the adapter requested
    immediately beforehand (``cairn_adapters.provider_execution.token.
    TokenProvider``) -- this protocol never accepts anything the adapter
    would need to hold onto across calls.
    """

    def apply(
        self, path: str, *, body: Mapping[str, object], token: str
    ) -> GcpExecutionResponse: ...

    def rollback(
        self, path: str, *, body: Mapping[str, object], token: str
    ) -> GcpExecutionResponse: ...


__all__ = ["GcpExecutionClient", "GcpExecutionResponse"]
