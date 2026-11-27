"""R6-06: which ``ModelPort`` adapter a deployment wires up.

``CAIRN_MODEL_ADAPTER`` selects, and its default is ``"fake"`` (design
§2) -- a test, a clean clone and ``make test`` never reach Vertex. A
deployment opts in to the real provider explicitly; selecting
``"vertex"`` with any of the three ``VertexGeminiSettings`` values
missing fails here, at startup, not at the first call a running agent
makes.
"""

from __future__ import annotations

import os

from cairn_kernel.errors import ConfigurationError
from cairn_kernel.model.ports import ModelPort

from cairn_adapters.model.fake import FakeModelAdapter
from cairn_adapters.model.vertex_gemini import VertexGeminiAdapter, VertexGeminiSettings

ENV_MODEL_ADAPTER = "CAIRN_MODEL_ADAPTER"

ADAPTER_FAKE = "fake"
ADAPTER_VERTEX = "vertex"


def resolve_model_adapter(env: dict[str, str] | None = None) -> ModelPort:
    """Build the ``ModelPort`` adapter named by ``CAIRN_MODEL_ADAPTER``.

    Unset (or anything blank) resolves to :class:`FakeModelAdapter` --
    the mandatory, deterministic default. ``"vertex"`` builds
    :class:`VertexGeminiAdapter` from :meth:`VertexGeminiSettings.from_env`,
    which itself raises ``ConfigurationError`` if any of the three
    required settings is missing. Any other value is rejected outright,
    the same fail-loudly shape.
    """

    source = env if env is not None else os.environ
    name = source.get(ENV_MODEL_ADAPTER, "").strip() or ADAPTER_FAKE
    if name == ADAPTER_FAKE:
        return FakeModelAdapter()
    if name == ADAPTER_VERTEX:
        settings = VertexGeminiSettings.from_env(source)
        return VertexGeminiAdapter(settings)
    raise ConfigurationError(
        f"{ENV_MODEL_ADAPTER}={name!r} is not a recognised model adapter "
        f"(expected {ADAPTER_FAKE!r} or {ADAPTER_VERTEX!r})"
    )


__all__ = ["ADAPTER_FAKE", "ADAPTER_VERTEX", "ENV_MODEL_ADAPTER", "resolve_model_adapter"]
