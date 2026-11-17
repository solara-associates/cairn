"""R-AI-01: model output schema validation.

A minimal, dependency-free validator against the object-shaped JSON-Schema
subset ``StructuredOutputExpectation.schema`` declares (required fields,
per-field primitive types). Invalid-shaped output is rejected here, before
it is handed back to any caller -- it is never silently passed through
(ADR-014, R-AI-01).
"""

from __future__ import annotations

from collections.abc import Mapping

from cairn_kernel.errors import ModelSchemaValidationError
from cairn_kernel.model.ports import StructuredOutputExpectation

_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (Mapping,),
    "array": (list, tuple),
}

# JSON Schema's "integer"/"number" never match a bool, even though ``bool``
# is a ``int`` subclass in Python.
_NEVER_BOOL_TYPES = frozenset({"integer", "number"})


def validate_structured_output(expectation: StructuredOutputExpectation, output: object) -> None:
    """Raise ``ModelSchemaValidationError`` unless ``output`` satisfies
    ``expectation``. Checks, in order: ``output`` is an object; every
    ``required`` field is present; every field named in ``properties``
    matches its declared primitive type when present."""

    schema_name = expectation.schema_name
    if not isinstance(output, Mapping):
        raise ModelSchemaValidationError(
            f"{schema_name}: model output must be an object, got {type(output).__name__}"
        )

    required = expectation.schema.get("required", [])
    if not isinstance(required, list):
        required = []
    missing = [name for name in required if name not in output]
    if missing:
        raise ModelSchemaValidationError(
            f"{schema_name}: missing required field(s) {sorted(missing)}"
        )

    properties = expectation.schema.get("properties", {})
    if not isinstance(properties, Mapping):
        properties = {}

    for name, value in output.items():
        field_schema = properties.get(name)
        if not isinstance(field_schema, Mapping):
            continue
        expected_type = field_schema.get("type")
        checks = _TYPE_CHECKS.get(expected_type) if isinstance(expected_type, str) else None
        if checks is None:
            continue
        if expected_type in _NEVER_BOOL_TYPES and isinstance(value, bool):
            raise ModelSchemaValidationError(
                f"{schema_name}: field {name!r} expected {expected_type}, got bool"
            )
        if not isinstance(value, checks):
            raise ModelSchemaValidationError(
                f"{schema_name}: field {name!r} expected {expected_type},"
                f" got {type(value).__name__}"
            )


__all__ = ["validate_structured_output"]
