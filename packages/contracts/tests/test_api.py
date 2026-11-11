import json
from pathlib import Path

import pytest
from cairn_contracts.api import (
    API_VERSION,
    BASE_PATH,
    ApiErrorCode,
    Operation,
    OperationState,
    Page,
    Problem,
)
from cairn_contracts.estate import Workload
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def test_problem_round_trips() -> None:
    raw = (FIXTURES / "problem.json").read_text(encoding="utf-8")
    problem = Problem.model_validate_json(raw)
    reparsed = Problem.model_validate_json(problem.model_dump_json())
    assert reparsed == problem
    assert json.loads(problem.model_dump_json()) == json.loads(raw)


def test_canonical_api_error_codes() -> None:
    assert {member.value for member in ApiErrorCode} == {
        "UNAUTHENTICATED",
        "FORBIDDEN",
        "TENANT_SCOPE_VIOLATION",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "IDEMPOTENCY_CONFLICT",
        "REVISION_MISMATCH",
        "MUTATION_CLASS_MISMATCH",
        "RECOVERY_PLAN_REQUIRED",
        "RISK_ACCEPTANCE_REQUIRED",
        "MAPPING_UNAVAILABLE",
        "EVIDENCE_VERIFICATION_FAILED",
        "AUDIT_UNAVAILABLE",
        "PROVIDER_UNAVAILABLE",
        "COVERAGE_INCOMPLETE",
    }


def test_problem_rejects_out_of_range_status() -> None:
    payload = json.loads((FIXTURES / "problem.json").read_text(encoding="utf-8"))
    payload["status"] = 399
    with pytest.raises(ValidationError):
        Problem.model_validate(payload)
    payload["status"] = 600
    with pytest.raises(ValidationError):
        Problem.model_validate(payload)


def test_problem_rejects_unknown_code() -> None:
    payload = json.loads((FIXTURES / "problem.json").read_text(encoding="utf-8"))
    payload["code"] = "NOT_A_CODE"
    with pytest.raises(ValidationError):
        Problem.model_validate(payload)


def test_page_of_workloads_round_trips() -> None:
    raw = (FIXTURES / "page.json").read_text(encoding="utf-8")
    page = Page[Workload].model_validate_json(raw)
    reparsed = Page[Workload].model_validate_json(page.model_dump_json())
    assert reparsed == page
    assert page.items[0].workload_id == "wl-0001"
    assert page.next_cursor == "cursor-2"


def test_operation_round_trips() -> None:
    raw = (FIXTURES / "operation.json").read_text(encoding="utf-8")
    operation = Operation.model_validate_json(raw)
    reparsed = Operation.model_validate_json(operation.model_dump_json())
    assert reparsed == operation
    assert operation.state is OperationState.RUNNING
    assert operation.progress == 0.4


def test_operation_rejects_out_of_range_progress() -> None:
    payload = json.loads((FIXTURES / "operation.json").read_text(encoding="utf-8"))
    payload["progress"] = 1.5
    with pytest.raises(ValidationError):
        Operation.model_validate(payload)


def test_operation_rejects_unknown_state() -> None:
    payload = json.loads((FIXTURES / "operation.json").read_text(encoding="utf-8"))
    payload["state"] = "PAUSED"
    with pytest.raises(ValidationError):
        Operation.model_validate(payload)


def test_api_version_is_pinned_to_v1() -> None:
    assert API_VERSION == "v1"
    assert BASE_PATH == "/v1"


def test_shared_api_models_expose_json_schemas() -> None:
    problem_schema = Problem.model_json_schema()
    assert problem_schema["required"] == [
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "trace_id",
        "code",
    ]
    operation_schema = Operation.model_json_schema()
    assert set(operation_schema["required"]) == {
        "operation_id",
        "state",
        "progress",
        "result_ref",
    }
    page_schema = Page[str].model_json_schema()
    assert set(page_schema["required"]) == {"items", "next_cursor"}
