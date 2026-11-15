"""R2-01 outbound port: spec section 5.4's ``MappingRepository``.

Spec 7.3: "The registry is read by assessment, TCO, design, diagram and
transformation through one ``MappingRepository`` port." ADR-004: "The
resolver is the only way modules obtain a mapping. Hard-coded service
maps in modules are forbidden." This is that one port -- every workflow
step (propose, review, publish, retire) plus every read a resolver or
console needs, with no other way in.
"""

from __future__ import annotations

from typing import Protocol

from cairn_contracts.mapping import MappingRelease
from cairn_kernel.hex import Port

from cairn_modules.mappings.domain import MappingProposalRecord, MappingReleaseRecord


class MappingRepository(Port, Protocol):
    def propose(
        self, release: MappingRelease, *, tenant_id: str, proposer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        """Record a brand-new release version as ``DRAFT`` then immediately
        submit it for review (``IN_REVIEW``) -- ADR-004's "propose" step --
        and record the tenant-scoped ``MappingProposalRecord`` alongside it
        (spec 8.1: a proposal is Tenant-owned even though the release
        content is Global). Raises ``ValidationError`` if ``release.
        version`` already exists or ``release.status`` is not ``DRAFT``.
        """

    def list_proposals(self, tenant_id: str) -> tuple[MappingProposalRecord, ...]:
        """Every proposal ``tenant_id`` has made, ordered by ``proposed_at``.

        Tenant-scoped (ADR-012): a repository must never return another
        tenant's proposals here, regardless of which tenant the caller
        claims to be -- a real adapter enforces this with RLS, the fake
        with the same ambient ``TenantContext`` check every other
        tenant-scoped in-memory repository in this codebase uses.
        """

    def review(
        self, version: str, *, approved: bool, reviewer_actor_id: str, rationale: str
    ) -> MappingReleaseRecord:
        """ADR-004's "review" step: approve (``IN_REVIEW`` -> ``APPROVED``)
        or reject (``IN_REVIEW`` -> ``DRAFT``, back to the author). Raises
        ``InvalidStateTransitionError`` unless the release is ``IN_REVIEW``,
        and ``MappingUnavailableError`` if ``version`` does not exist.
        """

    def publish(
        self, version: str, *, content_hash: str, actor_id: str, rationale: str = ""
    ) -> MappingReleaseRecord:
        """ADR-004's "publish" step: ``APPROVED`` -> ``PUBLISHED``.

        ``content_hash`` must match the release's proposed content exactly
        -- a mismatch raises ``ValidationError`` regardless of the
        release's current status, including when it is already
        ``PUBLISHED`` (today's ``InMemoryMappingRegistry`` immutability
        check, carried over unchanged). Calling this on an already-
        ``PUBLISHED`` version with the *same* ``content_hash`` is a no-op
        that returns the existing record. Calling it when the release is
        not ``APPROVED`` (and not already ``PUBLISHED``) raises
        ``ValidationError``.
        """

    def retire(self, version: str, *, actor_id: str, rationale: str) -> MappingReleaseRecord:
        """ADR-004's "retire" step: ``PUBLISHED`` -> ``RETIRED`` (terminal).

        Raises ``InvalidStateTransitionError`` unless the release is
        ``PUBLISHED``, and ``MappingUnavailableError`` if ``version`` does
        not exist.
        """

    def get(self, version: str) -> MappingReleaseRecord:
        """Raises ``MappingUnavailableError`` if ``version`` does not exist."""

    def get_published(self, version: str) -> MappingRelease:
        """The resolver's own read path: raises ``MappingUnavailableError``
        if ``version`` does not exist or is not currently ``PUBLISHED`` --
        spec 7.3's "UNAVAILABLE fails generation with an explanation; it
        never invents a substitute" starts here, before the resolver even
        looks at individual entries.
        """

    def list_releases(self) -> tuple[MappingReleaseRecord, ...]:
        """Every release this repository knows about, ordered by version."""


__all__ = ["MappingRepository"]
