"""R2-02: drives the real top-40 seed service map (the real candidate
content, not a synthetic fixture) through 700/R2-01's actual
propose/review/approve/publish/retire workflow -- but only as far as
ADR-004 allows a session to go on its own: `propose`, which both records
the release as ``DRAFT`` and immediately submits it for review
(``IN_REVIEW``), per ``MappingRepository.propose``'s own docstring.

This is deliberately *not* where the mechanism itself (every legal and
illegal transition, publish immutability, resolver behaviour, RBAC and
outbox wiring) is proven -- that is
`packages/modules/tests/test_mapping_workflow.py`, entirely against
`FakeMappingRepository` and a clearly synthetic fixture release (same
split R0-19 and R1-21 used between "the mechanism is proven" and "the
real content is Allan's call"). This file proves one additional thing
only: that the real seed content loaded from `mappings/service-map.yaml`
is itself a valid `MappingRelease` that the real `MappingService`/
`MappingRepository` code path accepts, and that it is proposed and left
``IN_REVIEW`` -- never approved, published or retired. No test in this
file calls `MappingRepository.publish`, `MappingService.publish`, or
`require_platform_operator`/`PLATFORM_OPERATOR`-gated anything, with real
candidate content or otherwise. The real publish decision belongs to
Allan Smeyatsky alone (ADR-004's named-approver requirement) and is not
exercised by this session, in tests or otherwise.
"""

from __future__ import annotations

from pathlib import Path

from cairn_contracts.mapping import ReleaseStatus
from cairn_kernel.hex import TenantId
from cairn_kernel.outbox import InMemoryOutboxStore, OutboxStatus
from cairn_kernel.security import Principal, Role
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.mappings import FakeMappingRepository, MappingService

REPO_ROOT = Path(__file__).parents[3]
SEED_PATH = REPO_ROOT / "mappings" / "service-map.yaml"

PILOT_TENANT = "33333333-3333-3333-3333-333333333333"


def _architect_principal() -> Principal:
    return Principal(subject="architect-pilot-1", tenant_id=TenantId(PILOT_TENANT), roles=(Role.ARCHITECT,))


def _tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(PILOT_TENANT),
        project_id=None,
        actor_id="architect-pilot-1",
        actor_roles=("ARCHITECT",),
        correlation_id="r2-02-seed-propose",
    )


def test_real_seed_content_proposes_cleanly_through_the_real_service() -> None:
    from cairn_modules.mappings import load_mapping_release

    release = load_mapping_release(SEED_PATH)
    repo = FakeMappingRepository()
    service = MappingService(repo, outbox=InMemoryOutboxStore())
    principal = _architect_principal()

    with tenant_scope(_tenant_context()):
        record = service.propose(
            principal,
            release=release,
            rationale="R2-02: seed service map for the AWS->GCP and Azure->GCP pilot pairs",
        )

    assert record.version == release.version
    assert record.content_hash == release.content_hash


def test_real_seed_content_reaches_in_review_and_stops_there() -> None:
    from cairn_modules.mappings import load_mapping_release

    release = load_mapping_release(SEED_PATH)
    repo = FakeMappingRepository()
    service = MappingService(repo, outbox=InMemoryOutboxStore())
    principal = _architect_principal()

    with tenant_scope(_tenant_context()):
        service.propose(principal, release=release, rationale="pilot seed, Allan's review pending")

    record = repo.get(release.version)
    assert record.status is ReleaseStatus.IN_REVIEW
    # Exactly the DRAFT -> IN_REVIEW transition pair `propose` makes in one
    # call (MappingRepository.propose's docstring) -- nothing further.
    assert [r.to_status for r in record.reviews] == [ReleaseStatus.DRAFT, ReleaseStatus.IN_REVIEW]


def test_real_seed_content_proposal_is_recorded_for_the_proposing_tenant() -> None:
    from cairn_modules.mappings import load_mapping_release

    release = load_mapping_release(SEED_PATH)
    repo = FakeMappingRepository()
    service = MappingService(repo, outbox=InMemoryOutboxStore())
    principal = _architect_principal()

    with tenant_scope(_tenant_context()):
        service.propose(principal, release=release, rationale="pilot seed")
        proposals = repo.list_proposals(PILOT_TENANT)

    assert len(proposals) == 1
    assert proposals[0].version == release.version


def test_real_seed_content_emits_exactly_one_proposed_event_no_published_event() -> None:
    from cairn_modules.mappings import load_mapping_release

    release = load_mapping_release(SEED_PATH)
    repo = FakeMappingRepository()
    outbox = InMemoryOutboxStore()
    service = MappingService(repo, outbox=outbox)
    principal = _architect_principal()

    with tenant_scope(_tenant_context()):
        service.propose(principal, release=release, rationale="pilot seed")

    pending = outbox.claim_pending()
    assert [message.event_type for message in pending] == ["mapping.proposed.v1"]
    assert pending[0].status is OutboxStatus.PENDING
    assert not any(message.event_type == "mapping.release.published.v1" for message in pending)
