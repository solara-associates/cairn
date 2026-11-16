"""R3-03b: ``TransformationPort`` adapters (spec §5.4) -- a real adapter
that shells out to the compiled ``cairn-transform-cli`` Rust binary (the
subprocess boundary over 722's versioned JSON contract, per this plan's
§7 open-question 1 resolution -- no FFI extension module, no shared
memory) and a deterministic fake for Python-side tests that never
actually shells out."""

from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_adapters.transform_core.subprocess_adapter import (
    SubprocessTransformationPort,
    TransformCliUnavailableError,
)

__all__ = [
    "FakeTransformationPort",
    "SubprocessTransformationPort",
    "TransformCliUnavailableError",
]
