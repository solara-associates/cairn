"""R5-02a: ``ModelPort`` contract, schema validation (R-AI-01) and the
import-boundary half of the R-AI-02 structural proof.

The full R-AI-02 proof -- that a ``ModelResponse`` cannot become an
approved/executed action without passing through the existing approval and
execution machinery -- composes this package's types with
``cairn_modules.approvals``/``cairn_modules.execution``, which this kernel
package itself must never import (the kernel is a leaf). That half lives in
``packages/modules/tests/test_model_proposal_boundary.py``, where the
import is legitimate. This file proves the other half: the import itself is
structurally absent from ``cairn_kernel.model``, and the port/response
types expose no authority-granting method or field at all.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path

import pytest
from cairn_kernel.errors import ModelSchemaValidationError, ValidationError
from cairn_kernel.model import (
    ModelPort,
    ModelRequest,
    ModelResponse,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
    validate_structured_output,
)

MODEL_SRC = Path(__file__).parents[1] / "src" / "cairn_kernel" / "model"


def _safety() -> SafetyParameters:
    return SafetyParameters(max_output_tokens=256)


def _expectation(**schema_overrides: object) -> StructuredOutputExpectation:
    schema: dict[str, object] = {
        "type": "object",
        "required": ["summary", "confidence"],
        "properties": {
            "summary": {"type": "string"},
            "confidence": {"type": "number"},
            "flagged": {"type": "boolean"},
        },
    }
    schema.update(schema_overrides)
    return StructuredOutputExpectation(schema_name="assessment.v1", schema=schema)


def _request(**overrides: object) -> ModelRequest:
    kwargs: dict[str, object] = {
        "prompt": "summarise the workload",
        "structured_output": _expectation(),
        "safety": _safety(),
        "tenant_id": "tenant-1",
        "correlation_id": "corr-1",
    }
    kwargs.update(overrides)
    return ModelRequest(**kwargs)  # type: ignore[arg-type]


def _response(**overrides: object) -> ModelResponse:
    kwargs: dict[str, object] = {
        "output": {"summary": "ok", "confidence": 0.9},
        "provider": "fake",
        "model": "fake-model-v1",
        "input_tokens": 10,
        "output_tokens": 5,
        "latency_ms": 12,
        "safety": SafetyMetadata(flagged=False),
        "correlation_id": "corr-1",
        "tenant_id": "tenant-1",
    }
    kwargs.update(overrides)
    return ModelResponse(**kwargs)  # type: ignore[arg-type]


# --- request/response contract ---------------------------------------------


def test_model_request_rejects_blank_prompt() -> None:
    with pytest.raises(ValidationError):
        _request(prompt="   ")


def test_model_request_rejects_blank_tenant_id() -> None:
    with pytest.raises(ValidationError):
        _request(tenant_id="")


def test_structured_output_expectation_requires_object_type() -> None:
    with pytest.raises(ValidationError):
        StructuredOutputExpectation(schema_name="x", schema={"type": "array"})


def test_safety_parameters_rejects_non_positive_max_tokens() -> None:
    with pytest.raises(ValidationError):
        SafetyParameters(max_output_tokens=0)


def test_model_response_rejects_blank_provider() -> None:
    with pytest.raises(ValidationError):
        _response(provider="")


def test_model_response_rejects_negative_latency() -> None:
    with pytest.raises(ValidationError):
        _response(latency_ms=-1)


# --- schema validation (R-AI-01) --------------------------------------------


def test_valid_output_passes_schema_validation() -> None:
    validate_structured_output(_expectation(), {"summary": "ok", "confidence": 0.5})


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ModelSchemaValidationError):
        validate_structured_output(_expectation(), {"summary": "ok"})


def test_wrong_field_type_is_rejected() -> None:
    with pytest.raises(ModelSchemaValidationError):
        validate_structured_output(_expectation(), {"summary": "ok", "confidence": "high"})


def test_boolean_is_not_accepted_as_a_number() -> None:
    with pytest.raises(ModelSchemaValidationError):
        validate_structured_output(_expectation(), {"summary": "ok", "confidence": True})


def test_non_object_output_is_rejected() -> None:
    with pytest.raises(ModelSchemaValidationError):
        validate_structured_output(_expectation(), ["not", "an", "object"])


def test_malformed_output_is_rejected_not_passed_through() -> None:
    """R-AI-01: invalid-shaped output is rejected, never silently passed
    through to whatever would consume it."""

    malformed = {"summary": 123, "confidence": 0.9}
    with pytest.raises(ModelSchemaValidationError):
        validate_structured_output(_expectation(), malformed)


# --- R-AI-02: the port's own shape grants no authority ----------------------


def test_model_port_protocol_exposes_exactly_one_method() -> None:
    public_members = {name for name in dir(ModelPort) if not name.startswith("_")}
    assert public_members == {"generate"}


def test_model_response_has_no_authority_granting_field() -> None:
    forbidden_substrings = ("approve", "execute", "authoriz", "adapter", "credential")
    field_names = {f.name for f in dataclasses.fields(ModelResponse)}
    for name in field_names:
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), name


def test_model_response_exposes_no_approve_or_execute_method() -> None:
    public_methods = {
        name
        for name in dir(ModelResponse)
        if not name.startswith("_") and callable(getattr(ModelResponse, name, None))
    }
    assert public_methods == set()


def test_model_request_has_no_field_naming_a_resource_to_mutate() -> None:
    forbidden_substrings = ("approve", "execute", "authoriz", "credential", "resource_id")
    field_names = {f.name for f in dataclasses.fields(ModelRequest)}
    for name in field_names:
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), name


# --- R-AI-02: no import path from here into execution/approval -------------

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "cairn_kernel",
    "collections",
    "dataclasses",
    "datetime",
    "enum",
    "hashlib",
    "types",
    "typing",
}

_FORBIDDEN_IMPORT_ROOTS = {
    # Nothing in cairn_kernel.model may import the execution gate or any
    # approval/execution module -- that would be the one path through
    # which a model response could reach authority to act, and R-AI-02
    # requires it to not exist.
    "cairn_modules",
}


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_submodules(tree: ast.Module, root: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(root):
            modules.add(node.module)
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith(root))
    return modules


def test_model_package_never_imports_approvals_or_execution_modules() -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(MODEL_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = roots & _FORBIDDEN_IMPORT_ROOTS
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"cairn_kernel.model must not import: {violations}"


def test_model_package_never_imports_the_execution_gate() -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(MODEL_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = _imported_submodules(tree, "cairn_kernel.execution_gate")
        if modules:
            violations[path.name] = modules
    assert not violations, f"cairn_kernel.model must not import the execution gate: {violations}"


def test_model_package_imports_only_stdlib_and_kernel() -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(MODEL_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in _ALLOWED_IMPORT_ROOTS
        }
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"disallowed imports in cairn_kernel.model: {violations}"
