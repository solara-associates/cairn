from types import MappingProxyType

import pytest
from cairn_kernel.hex import OperationClass, TenantId
from cairn_kernel.security import AuditEntry, CanonicalJSONError, canonical_json


def test_canonical_json_sorts_keys_and_matches_across_insertion_order() -> None:
    first = canonical_json({"b": 1, "a": {"d": 2, "c": [3, 4]}})
    second = canonical_json({"a": {"c": [3, 4], "d": 2}, "b": 1})
    assert first == second == '{"a":{"c":[3,4],"d":2},"b":1}'


def test_canonical_json_preserves_unicode_and_escapes_strings() -> None:
    assert canonical_json({"name": "café"}) == '{"name":"café"}'
    assert canonical_json("line\nbreak") == '"line\\nbreak"'


def test_canonical_json_rejects_unsupported_values() -> None:
    for value in (float("nan"), float("inf"), b"bytes", {1: "non-string key"}, object()):
        with pytest.raises(CanonicalJSONError):
            canonical_json({"value": value})
    with pytest.raises(CanonicalJSONError):
        canonical_json(2**53)


def test_freeze_json_makes_nested_containers_immutable() -> None:
    entry = AuditEntry(
        tenant_id=TenantId("11111111-1111-4111-8111-111111111111"),
        project_id=None,
        actor="user-1",
        action="project.update",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"nested": {"items": [1, 2]}},
    )
    assert isinstance(entry.payload, MappingProxyType)
    assert entry.payload["nested"]["items"] == (1, 2)
    with pytest.raises(TypeError):
        entry.payload["nested"]["items"] = ()  # type: ignore[index]


def test_audit_entry_ignores_later_mutation_of_the_input() -> None:
    source: dict[str, object] = {"after": {"name": "before"}}
    entry = AuditEntry(
        tenant_id=TenantId("11111111-1111-4111-8111-111111111111"),
        project_id=None,
        actor="user-1",
        action="project.update",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload=source,
    )
    canonical = entry.payload_json
    source["after"] = {"name": "tampered"}
    assert entry.payload_json == canonical == '{"after":{"name":"before"}}'


def test_audit_entry_records_the_correlation_id_in_the_hashed_payload() -> None:
    entry = AuditEntry(
        tenant_id=TenantId("11111111-1111-4111-8111-111111111111"),
        project_id=None,
        actor="user-1",
        action="project.update",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"changed": ["name"]},
        correlation_id="corr-1",
    )
    assert entry.payload_json == '{"changed":["name"],"correlation_id":"corr-1"}'
