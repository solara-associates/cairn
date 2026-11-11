import pytest
from cairn_kernel.errors import (
    AuditUnavailableError,
    CairnError,
    CoverageIncompleteError,
    ErrorCode,
    EvidenceVerificationFailedError,
    ForbiddenError,
    IdempotencyConflictError,
    MappingUnavailableError,
    MutationClassMismatchError,
    NotFoundError,
    ProviderUnavailableError,
    RecoveryPlanRequiredError,
    RevisionMismatchError,
    RiskAcceptanceRequiredError,
    TenantScopeViolationError,
    UnauthenticatedError,
    ValidationError,
)

CANONICAL_ERRORS = [
    (UnauthenticatedError, ErrorCode.UNAUTHENTICATED),
    (ForbiddenError, ErrorCode.FORBIDDEN),
    (TenantScopeViolationError, ErrorCode.TENANT_SCOPE_VIOLATION),
    (NotFoundError, ErrorCode.NOT_FOUND),
    (ValidationError, ErrorCode.VALIDATION_FAILED),
    (IdempotencyConflictError, ErrorCode.IDEMPOTENCY_CONFLICT),
    (RevisionMismatchError, ErrorCode.REVISION_MISMATCH),
    (MutationClassMismatchError, ErrorCode.MUTATION_CLASS_MISMATCH),
    (RecoveryPlanRequiredError, ErrorCode.RECOVERY_PLAN_REQUIRED),
    (RiskAcceptanceRequiredError, ErrorCode.RISK_ACCEPTANCE_REQUIRED),
    (MappingUnavailableError, ErrorCode.MAPPING_UNAVAILABLE),
    (EvidenceVerificationFailedError, ErrorCode.EVIDENCE_VERIFICATION_FAILED),
    (AuditUnavailableError, ErrorCode.AUDIT_UNAVAILABLE),
    (ProviderUnavailableError, ErrorCode.PROVIDER_UNAVAILABLE),
    (CoverageIncompleteError, ErrorCode.COVERAGE_INCOMPLETE),
]


@pytest.mark.parametrize("error_type,expected_code", CANONICAL_ERRORS)
def test_canonical_error_codes(error_type: type, expected_code: ErrorCode) -> None:
    error = error_type("detail text")
    assert isinstance(error, CairnError)
    assert isinstance(error, Exception)
    assert error.code is expected_code
    assert error.title
    assert str(error) == "detail text"


def test_error_str_falls_back_to_title_without_detail() -> None:
    assert str(NotFoundError()) == NotFoundError.title


def test_canonical_codes_are_unique() -> None:
    codes = [code for _, code in CANONICAL_ERRORS]
    assert len(codes) == len(set(codes))
