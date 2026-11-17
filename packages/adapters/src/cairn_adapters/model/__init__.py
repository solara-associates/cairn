"""CAIRN cairn_adapters.model: the mandatory fake ``ModelPort`` adapter
(ADR-014, R5-02a). No real provider adapter exists in this unit --
``ModelGateway``/``ModelPort`` are provider-agnostic, and a Gemini adapter
is left to a later unit per ADR-014's launch scope.
"""

from cairn_adapters.model.fake import FAKE_MODEL, FAKE_PROVIDER, FakeModelAdapter

__all__ = ["FAKE_MODEL", "FAKE_PROVIDER", "FakeModelAdapter"]
