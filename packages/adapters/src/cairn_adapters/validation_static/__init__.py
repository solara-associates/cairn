"""R3-05: the "static" half of ``ValidationPort`` (spec §5.4). A real
subprocess adapter wrapping ``cairn-transform-validator-cli`` (729's new
Rust binary -- see ``packages/transform-core/validator``), plus a
deterministic fake for tests."""

from cairn_adapters.validation_static.fake import FakeStaticValidationAdapter
from cairn_adapters.validation_static.subprocess_adapter import (
    StaticValidationAdapter,
    ValidatorCliUnavailableError,
    resolve_validator_cli_binary,
)

__all__ = [
    "FakeStaticValidationAdapter",
    "StaticValidationAdapter",
    "ValidatorCliUnavailableError",
    "resolve_validator_cli_binary",
]
