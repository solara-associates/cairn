from enum import Enum


class ErrorCode(str, Enum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_SCOPE_VIOLATION = "TENANT_SCOPE_VIOLATION"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    MUTATION_CLASS_MISMATCH = "MUTATION_CLASS_MISMATCH"
    RECOVERY_PLAN_REQUIRED = "RECOVERY_PLAN_REQUIRED"
    RISK_ACCEPTANCE_REQUIRED = "RISK_ACCEPTANCE_REQUIRED"
    MAPPING_UNAVAILABLE = "MAPPING_UNAVAILABLE"
    CONTROL_UNAVAILABLE = "CONTROL_UNAVAILABLE"
    PRICE_LIST_UNAVAILABLE = "PRICE_LIST_UNAVAILABLE"
    EVIDENCE_VERIFICATION_FAILED = "EVIDENCE_VERIFICATION_FAILED"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    SEPARATION_OF_DUTIES_VIOLATION = "SEPARATION_OF_DUTIES_VIOLATION"
    INTERNAL = "INTERNAL"


class CairnError(Exception):
    code = ErrorCode.INTERNAL
    title = "Internal error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail or self.title


class UnauthenticatedError(CairnError):
    code = ErrorCode.UNAUTHENTICATED
    title = "Unauthenticated"


class ForbiddenError(CairnError):
    code = ErrorCode.FORBIDDEN
    title = "Forbidden"


class TenantScopeViolationError(CairnError):
    code = ErrorCode.TENANT_SCOPE_VIOLATION
    title = "Tenant scope violation"


class NotFoundError(CairnError):
    code = ErrorCode.NOT_FOUND
    title = "Not found"


class ValidationError(CairnError):
    code = ErrorCode.VALIDATION_FAILED
    title = "Validation failed"


class IdempotencyConflictError(CairnError):
    code = ErrorCode.IDEMPOTENCY_CONFLICT
    title = "Idempotency conflict"


class RevisionMismatchError(CairnError):
    code = ErrorCode.REVISION_MISMATCH
    title = "Revision mismatch"


class MutationClassMismatchError(CairnError):
    code = ErrorCode.MUTATION_CLASS_MISMATCH
    title = "Mutation class mismatch"


class RecoveryPlanRequiredError(CairnError):
    code = ErrorCode.RECOVERY_PLAN_REQUIRED
    title = "Recovery plan required"


class RiskAcceptanceRequiredError(CairnError):
    code = ErrorCode.RISK_ACCEPTANCE_REQUIRED
    title = "Risk acceptance required"


class MappingUnavailableError(CairnError):
    code = ErrorCode.MAPPING_UNAVAILABLE
    title = "Mapping unavailable"


class ControlUnavailableError(CairnError):
    code = ErrorCode.CONTROL_UNAVAILABLE
    title = "Control unavailable"


class PriceListUnavailableError(CairnError):
    code = ErrorCode.PRICE_LIST_UNAVAILABLE
    title = "Price list unavailable"


class EvidenceVerificationFailedError(CairnError):
    code = ErrorCode.EVIDENCE_VERIFICATION_FAILED
    title = "Evidence verification failed"


class AuditUnavailableError(CairnError):
    code = ErrorCode.AUDIT_UNAVAILABLE
    title = "Audit unavailable"


class ProviderUnavailableError(CairnError):
    code = ErrorCode.PROVIDER_UNAVAILABLE
    title = "Provider unavailable"


class CoverageIncompleteError(CairnError):
    code = ErrorCode.COVERAGE_INCOMPLETE
    title = "Coverage incomplete"


class InvalidStateTransitionError(CairnError):
    code = ErrorCode.INVALID_STATE_TRANSITION
    title = "Invalid state transition"


class SeparationOfDutiesError(CairnError):
    code = ErrorCode.SEPARATION_OF_DUTIES_VIOLATION
    title = "Separation of duties violation"


class ConfigurationError(CairnError):
    code = ErrorCode.INTERNAL
    title = "Configuration error"


class MissingDependencyError(CairnError):
    code = ErrorCode.INTERNAL
    title = "Missing dependency"
