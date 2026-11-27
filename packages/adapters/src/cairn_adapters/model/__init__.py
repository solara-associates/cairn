"""CAIRN cairn_adapters.model: the mandatory fake ``ModelPort`` adapter
(ADR-014, R5-02a) and R6-06's real one, ``VertexGeminiAdapter``.
``FakeModelAdapter`` stays the default: ``resolve_model_adapter`` (R6-06)
only builds the Vertex adapter when ``CAIRN_MODEL_ADAPTER=vertex`` is set
explicitly.
"""

from cairn_adapters.model.fake import FAKE_MODEL, FAKE_PROVIDER, FakeModelAdapter
from cairn_adapters.model.selection import (
    ADAPTER_FAKE,
    ADAPTER_VERTEX,
    ENV_MODEL_ADAPTER,
    resolve_model_adapter,
)
from cairn_adapters.model.vertex_gemini import (
    ENV_LOCATION,
    ENV_MODEL,
    ENV_PROJECT,
    VertexGeminiAdapter,
    VertexGeminiSettings,
    price_rate_for_model,
    register_vertex_price,
)
from cairn_adapters.model.vertex_gemini import (
    PROVIDER as VERTEX_PROVIDER,
)

__all__ = [
    "ADAPTER_FAKE",
    "ADAPTER_VERTEX",
    "ENV_LOCATION",
    "ENV_MODEL",
    "ENV_MODEL_ADAPTER",
    "ENV_PROJECT",
    "FAKE_MODEL",
    "FAKE_PROVIDER",
    "VERTEX_PROVIDER",
    "FakeModelAdapter",
    "VertexGeminiAdapter",
    "VertexGeminiSettings",
    "price_rate_for_model",
    "register_vertex_price",
    "resolve_model_adapter",
]
