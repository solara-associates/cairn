"""R2-01: the mapping registry workflow's domain shapes.

``MappingReleaseRecord`` is what a ``MappingRepository`` returns: the
release's immutable proposed content (``release``) plus its current
ADR-004 workflow status and full review history, derived separately from
that content (see migration 0007's docstring for why the two are split --
in short, ``MappingRelease.content_hash`` includes the model's ``status``
field, so a release's *content* fingerprint has to stay pinned to one
fixed status value, never the one it currently happens to be in).

``ALLOWED_TRANSITIONS``/``require_legal_transition`` is the identical
ADR-004 sequence migration 0007's ``mapping_release_review_enforce_
sequence`` trigger enforces at the database -- kept here, in one place,
so ``FakeMappingRepository`` and ``PostgresMappingRepository`` can never
silently disagree with each other or with the trigger about what counts
as a legal transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import InvalidStateTransitionError

ALLOWED_TRANSITIONS: dict[ReleaseStatus | None, tuple[ReleaseStatus, ...]] = {
    None: (ReleaseStatus.DRAFT,),
    ReleaseStatus.DRAFT: (ReleaseStatus.IN_REVIEW,),
    ReleaseStatus.IN_REVIEW: (ReleaseStatus.APPROVED, ReleaseStatus.DRAFT),
    ReleaseStatus.APPROVED: (ReleaseStatus.PUBLISHED,),
    ReleaseStatus.PUBLISHED: (ReleaseStatus.RETIRED,),
    ReleaseStatus.RETIRED: (),
}


def require_legal_transition(
    current: ReleaseStatus | None, target: ReleaseStatus, *, version: str
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, ())
    if target not in allowed:
        current_label = current.value if current is not None else "none"
        raise InvalidStateTransitionError(
            f"mapping release {version} cannot move from {current_label} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class MappingReleaseReview:
    """One ADR-004 propose/review/approve/publish/retire transition,
    the audit record the ADR requires: actor, timestamp and rationale.
    """

    from_status: ReleaseStatus | None
    to_status: ReleaseStatus
    actor_id: str
    rationale: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MappingReleaseRecord:
    """A mapping release as the workflow repository tracks it.

    ``release`` is the immutable content proposed for this version --
    always carrying ``ReleaseStatus.DRAFT`` regardless of the release's
    real current status (see module docstring); ``release.content_hash``
    is therefore the release's stable content fingerprint. ``status`` is
    the release's real, current ADR-004 workflow status, and ``reviews``
    is its full transition history in order.
    """

    release: MappingRelease
    status: ReleaseStatus
    reviews: tuple[MappingReleaseReview, ...]

    @property
    def version(self) -> str:
        return self.release.version

    @property
    def content_hash(self) -> str:
        return self.release.content_hash

    @property
    def is_published(self) -> bool:
        return self.status is ReleaseStatus.PUBLISHED


@dataclass(frozen=True, slots=True)
class MappingProposalRecord:
    """The tenant-scoped half of ADR-004's "propose" step (spec 8.1: "tenant
    mapping proposals" is Tenant-owned, not Global). Records which tenant
    asked for ``version`` and why -- the release content itself lands in
    the global ``MappingReleaseRecord`` at the same time, in the same
    ``MappingRepository.propose`` call, and is visible to every tenant
    once it exists; this record is visible only to the tenant that made
    it (``MappingRepository.list_proposals`` is tenant-scoped).
    """

    proposal_id: str
    tenant_id: str
    version: str
    proposer_actor_id: str
    rationale: str
    proposed_at: datetime


__all__ = [
    "ALLOWED_TRANSITIONS",
    "MappingProposalRecord",
    "MappingReleaseRecord",
    "MappingReleaseReview",
    "require_legal_transition",
]
