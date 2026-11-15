"""R2-01: the mapping registry workflow (ADR-004 propose/review/approve/
publish/retire), the resolver (spec 9.3), and the ``MappingService``
RBAC + outbox wiring.

Pure in-process tests against ``FakeMappingRepository`` -- the Postgres
adapter's equivalent behaviour is proven live against Postgres in
``tests/integration/test_mapping_release_schema.py``. Tenant isolation
here mirrors ``packages/kernel/tests/test_tenancy_isolation.py``'s
pattern via the ambient ``TenantContext`` (ADR-012), the same way
``packages/modules/tests/test_projects.py`` proves it for
``InMemoryProjectRepository``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_kernel.errors import (
    ForbiddenError,
    InvalidStateTransitionError,
    MappingUnavailableError,
    TenantScopeViolationError,
    ValidationError,
)
from cairn_kernel.hex import TenantId
from cairn_kernel.outbox import InMemoryOutboxStore, OutboxStatus
from cairn_kernel.security import Principal, Role
from cairn_kernel.security.platform_operators import is_platform_operator
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.mappings import FakeMappingRepository, MappingService
from cairn_modules.mappings.resolver import resolve_mapping

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


def _principal(tenant: str, *roles: Role, subject: str = "user-1") -> Principal:
    return Principal(subject=subject, tenant_id=TenantId(tenant), roles=roles)


def _context(tenant: str, *roles: str, actor: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=None,
        actor_id=actor,
        actor_roles=roles,
        correlation_id="corr-1",
    )


def _entry(**overrides: object) -> MappingEntry:
    payload = {
        "id": "s3-to-gcs",
        "source_provider": "aws",
        "source_service": "s3",
        "target_provider": "gcp",
        "target_service": "cloud-storage",
        "equivalence": Equivalence.APPROXIMATE,
        "caveat": "Consistency semantics differ",
        "regions": ("europe-west2",),
        "evidence": "public documentation",
    }
    payload.update(overrides)
    return MappingEntry(**payload)


def _release(version: str = "2026.11.1", *entries: MappingEntry) -> MappingRelease:
    return MappingRelease(
        version=version,
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=entries or (_entry(),),
    )


def _service(repository: FakeMappingRepository | None = None) -> tuple[MappingService, InMemoryOutboxStore]:
    outbox = InMemoryOutboxStore()
    service = MappingService(repository or FakeMappingRepository(), outbox=outbox)
    return service, outbox


# --- repository workflow: legal/illegal transitions ------------------------


def test_propose_creates_an_in_review_release() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        record = repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="architect-1", rationale="pilot gap")

    assert record.status is ReleaseStatus.IN_REVIEW
    assert record.content_hash == release.content_hash
    assert [r.to_status for r in record.reviews] == [ReleaseStatus.DRAFT, ReleaseStatus.IN_REVIEW]


def test_propose_rejects_a_duplicate_version() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
        with pytest.raises(ValidationError):
            repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")


def test_propose_rejects_a_non_draft_release() -> None:
    repo = FakeMappingRepository()
    published = _release().model_copy(update={"status": ReleaseStatus.PUBLISHED})
    with tenant_scope(_context(TENANT_A)), pytest.raises(ValidationError):
        repo.propose(published, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")


def test_review_approve_moves_in_review_to_approved() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    record = repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="looks right")
    assert record.status is ReleaseStatus.APPROVED


def test_review_reject_sends_release_back_to_draft() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    record = repo.review(release.version, approved=False, reviewer_actor_id="approver-1", rationale="needs caveat")
    assert record.status is ReleaseStatus.DRAFT


def test_review_on_a_draft_release_is_illegal() -> None:
    # DRAFT only exists transiently inside propose(); reaching it again via
    # rejection and reviewing a second time before resubmission is illegal.
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=False, reviewer_actor_id="approver-1", rationale="no")
    with pytest.raises(InvalidStateTransitionError):
        repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="now yes")


def test_review_unknown_version_is_unavailable() -> None:
    repo = FakeMappingRepository()
    with pytest.raises(MappingUnavailableError):
        repo.review("2099.1.1", approved=True, reviewer_actor_id="a", rationale="r")


def test_publish_requires_approved() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    with pytest.raises(ValidationError, match="not APPROVED"):
        repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")


def test_publish_transitions_approved_to_published() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")

    record = repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    assert record.status is ReleaseStatus.PUBLISHED


def test_publish_same_version_different_hash_raises_even_when_already_published() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    with pytest.raises(ValidationError, match="immutable"):
        repo.publish(release.version, content_hash="not-the-real-hash", actor_id="operator-1")


def test_publish_same_version_same_hash_is_a_no_op() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    first = repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    second = repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    assert second.status is ReleaseStatus.PUBLISHED
    assert len(second.reviews) == len(first.reviews)  # no new transition row was recorded


def test_retire_requires_published() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    with pytest.raises(InvalidStateTransitionError):
        repo.retire(release.version, actor_id="operator-1", rationale="deprecated")


def test_retire_transitions_published_to_retired_and_is_terminal() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    record = repo.retire(release.version, actor_id="operator-1", rationale="superseded")
    assert record.status is ReleaseStatus.RETIRED

    with pytest.raises(InvalidStateTransitionError):
        repo.retire(release.version, actor_id="operator-1", rationale="again")


def test_get_unknown_release_is_unavailable() -> None:
    repo = FakeMappingRepository()
    with pytest.raises(MappingUnavailableError):
        repo.get("2099.1.1")


def test_list_releases_is_ordered_by_version() -> None:
    repo = FakeMappingRepository()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(_release("2026.11.2"), tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
        repo.propose(_release("2026.11.1"), tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")

    versions = [record.version for record in repo.list_releases()]
    assert versions == ["2026.11.1", "2026.11.2"]


# --- tenant isolation on proposals ------------------------------------------


def test_proposals_are_tenant_scoped() -> None:
    repo = FakeMappingRepository()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(_release(), tenant_id=TENANT_A, proposer_actor_id="a", rationale="pilot gap")
        tenant_a_proposals = repo.list_proposals(TENANT_A)

    assert len(tenant_a_proposals) == 1
    assert tenant_a_proposals[0].tenant_id == TENANT_A

    with tenant_scope(_context(TENANT_B)):
        tenant_b_proposals = repo.list_proposals(TENANT_B)

    assert tenant_b_proposals == ()


def test_cross_tenant_proposal_list_is_rejected_before_read() -> None:
    repo = FakeMappingRepository()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(_release(), tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
        with pytest.raises(TenantScopeViolationError):
            repo.list_proposals(TENANT_B)


def test_cross_tenant_propose_is_rejected_before_persistence() -> None:
    repo = FakeMappingRepository()
    with tenant_scope(_context(TENANT_A)), pytest.raises(TenantScopeViolationError):
        repo.propose(_release(), tenant_id=TENANT_B, proposer_actor_id="a", rationale="r")
    # nothing was persisted under either tenant
    with tenant_scope(_context(TENANT_B)):
        assert repo.list_proposals(TENANT_B) == ()


# --- resolver ----------------------------------------------------------------


def test_resolve_mapping_returns_spec_9_3_shape() -> None:
    release = _release().model_copy(update={"status": ReleaseStatus.PUBLISHED})

    resolved = resolve_mapping(
        release,
        source_provider="aws",
        source_service="s3",
        target_provider="gcp",
        region="europe-west2",
    )

    assert resolved.source_provider == "aws"
    assert resolved.source_service == "s3"
    assert resolved.target_provider == "gcp"
    assert resolved.target_service == "cloud-storage"
    assert resolved.equivalence is Equivalence.APPROXIMATE
    assert resolved.caveat == "Consistency semantics differ"
    assert resolved.region_supported is True
    assert resolved.mapping_version == release.version
    assert resolved.evidence == "public documentation"


def test_resolve_mapping_flags_unsupported_region() -> None:
    release = _release()

    resolved = resolve_mapping(
        release,
        source_provider="aws",
        source_service="s3",
        target_provider="gcp",
        region="asia-south1",
    )

    assert resolved.region_supported is False


def test_resolve_mapping_with_no_matching_entry_is_unavailable() -> None:
    release = _release()

    with pytest.raises(MappingUnavailableError):
        resolve_mapping(
            release, source_provider="aws", source_service="dynamodb", target_provider="gcp"
        )


def test_resolve_mapping_unavailable_equivalence_fails_with_explanation_never_a_substitute() -> None:
    entry = _entry(
        id="s3-object-lock-to-gcs-retention",
        source_service="s3-object-lock",
        target_service=None,
        equivalence=Equivalence.UNAVAILABLE,
        caveat="No exact equivalent for legal-hold semantics",
    )
    release = _release("2026.11.1", entry)

    with pytest.raises(MappingUnavailableError, match="legal-hold"):
        resolve_mapping(
            release, source_provider="aws", source_service="s3-object-lock", target_provider="gcp"
        )


# --- MappingService: RBAC and outbox events ---------------------------------


def test_resolve_requires_authentication_role_but_allows_any_tenant_role() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")
    service, _ = _service(repo)

    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")):
        resolved = service.resolve(
            viewer,
            mapping_version=release.version,
            source_provider="aws",
            source_service="s3",
            target_provider="gcp",
        )
    assert resolved.mapping_version == release.version


def test_propose_requires_architect_or_tenant_admin() -> None:
    service, _ = _service()
    engineer = _principal(TENANT_A, Role.ENGINEER)
    with tenant_scope(_context(TENANT_A, "ENGINEER")), pytest.raises(ForbiddenError):
        service.propose(engineer, release=_release(), rationale="pilot gap")


def test_propose_emits_mapping_proposed_event_via_outbox() -> None:
    service, outbox = _service()
    architect = _principal(TENANT_A, Role.ARCHITECT)
    with tenant_scope(_context(TENANT_A, "ARCHITECT")):
        service.propose(architect, release=_release(), rationale="pilot gap")

    pending = outbox.claim_pending()
    assert len(pending) == 1
    assert pending[0].event_type == "mapping.proposed.v1"
    assert pending[0].tenant_id == TENANT_A
    assert pending[0].status is OutboxStatus.PENDING


def test_publish_emits_mapping_release_published_event_via_outbox() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    service, outbox = _service(repo)
    operator = _principal(TENANT_A, subject="platform-op-1")

    service.publish(operator, version=release.version, content_hash=release.content_hash)

    pending = outbox.claim_pending()
    assert len(pending) == 1
    assert pending[0].event_type == "mapping.release.published.v1"


def test_publish_no_op_republish_does_not_emit_a_second_event() -> None:
    repo = FakeMappingRepository()
    release = _release()
    with tenant_scope(_context(TENANT_A)):
        repo.propose(release, tenant_id=TENANT_A, proposer_actor_id="a", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    service, outbox = _service(repo)
    operator = _principal(TENANT_A, subject="platform-op-1")

    service.publish(operator, version=release.version, content_hash=release.content_hash)
    service.publish(operator, version=release.version, content_hash=release.content_hash)

    assert len(outbox.claim_pending()) == 1


# --- PLATFORM_OPERATOR -------------------------------------------------------


def test_is_platform_operator_denies_by_default() -> None:
    assert is_platform_operator("someone", allowlist=()) is False


def test_is_platform_operator_allows_a_listed_subject() -> None:
    assert is_platform_operator("platform-op-1", allowlist=("platform-op-1",)) is True
