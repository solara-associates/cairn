from collections.abc import Awaitable, Callable
from typing import Any

from cairn_contracts.api import ApiErrorCode, Problem
from cairn_kernel.errors import CairnError, ErrorCode

Scope = dict[str, Any]
Message = dict[str, Any]

STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TENANT_SCOPE_VIOLATION: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.REVISION_MISMATCH: 409,
    ErrorCode.MUTATION_CLASS_MISMATCH: 422,
    ErrorCode.RECOVERY_PLAN_REQUIRED: 409,
    ErrorCode.RISK_ACCEPTANCE_REQUIRED: 403,
    ErrorCode.MAPPING_UNAVAILABLE: 409,
    ErrorCode.EVIDENCE_VERIFICATION_FAILED: 422,
    ErrorCode.AUDIT_UNAVAILABLE: 503,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.COVERAGE_INCOMPLETE: 422,
    ErrorCode.INTERNAL: 500,
}


def problem_from_error(error: CairnError, *, instance: str, trace_id: str) -> Problem:
    code = ApiErrorCode(error.code.value)
    return Problem(
        type=f"https://cairn.dev/problems/{code.value.lower().replace('_', '-')}",
        title=error.title,
        status=STATUS_BY_CODE[error.code],
        detail=str(error) or error.title,
        instance=instance,
        trace_id=trace_id,
        code=code,
    )


async def send_problem(
    scope: Scope,
    send: Callable[[Message], Awaitable[None]],
    error: CairnError,
    correlation_id: str,
) -> None:
    problem = problem_from_error(
        error,
        instance=scope.get("path", ""),
        trace_id=correlation_id,
    )
    await send(
        {
            "type": "http.response.start",
            "status": problem.status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"x-correlation-id", correlation_id.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": problem.model_dump_json().encode()})
