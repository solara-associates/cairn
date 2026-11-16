"""792 (R4-05): the approval and execution console -- approver's view
API routes.

Spec §2.4 (quoted verbatim in this unit's brief): "R4-05's console shows
the approver the exact revision: the diff, the mutation class, the
recovery plan (rollback or compensation contract, ADR-010), and the
evidence that will be captured. Nothing is approved from a summary -- the
approver sees what will actually run." This module's two GET-shaped
reads surface exactly those four things, assembled from:

- 787's ``orchestrate_terraform_plan``/``TerraformPlanRevisionPayload``
  (``cairn_adapters.iac_terraform``) -- the exact revision, its diff and
  its mutation class, orchestrated here against
  ``cairn_adapters.provider_execution.FakeProviderExecutionAdapter``
  (this unit is explicitly "no cloud" -- built against the fake adapter
  only; a real provider adapter is never wired into this module).
- 783's ``cairn_kernel.classification.model.CompensationContract`` (the
  "recovery plan": rollback or compensation contract, ADR-010) -- this
  module never calls 790's ``RecoveryEngine`` (that engine only runs
  *after* a real execution has started failing; this console is reached
  *before* any execution is authorized at all), it only displays the
  contract that engine would be bound to use if recovery were ever
  needed.
- ADR-010's own "Evidence" column ("what must be captured before,
  during and after the effect") -- read directly off
  ``CompensationContract.evidence``, the one field that field is for;
  not a second, independently-invented description of the same thing.

``cairn_modules.approval_console.ensure_recovery_plan_complete`` is
called again, at this console's own decision route, immediately before
an ``APPROVE`` decision would be recorded -- this unit's own acceptance
text: "a deliberate-break test proves an incomplete recovery plan cannot
be approved from the console (mirrors 783's gate, enforced again at the
UI layer so a UI bug can't bypass the kernel constraint)". A failing
check raises before any comment is appended -- no partial state, the
same "fail closed, no external effect" discipline every gate in this
codebase already follows.

Tenant isolation, role gating and the registry-vs-real-repository split
all follow ``routes_transformations.py``'s own discipline exactly (see
that module's docstring for the full reasoning) -- not re-derived here.
``CREATE_ROLES``/``READ_ROLES`` are the identical tuples that module
already defines for the identical spec §12.1 cells ("ENGINEER+" to
create, "VIEWER+" to read); ``REVIEW_ROLES`` is the identical
``ENGINEER+`` plus ``Role.REVIEWER`` reasoning that module's own
docstring already names for spec §12.1's REVIEWER row.
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cairn_adapters.iac_terraform import TerraformPlanRevisionPayload, orchestrate_terraform_plan
from cairn_adapters.provider_execution import FakeProviderExecutionAdapter, ProviderExecutionPort
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.hex.ports import Clock, SystemClock
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.security import Principal, Role, require_roles
from cairn_modules.approval_console.model import (
    ApprovalComment,
    PlanApprovalThread,
    ReviewDecisionKind,
    add_approval_comment,
    ensure_recovery_plan_complete,
)
from cairn_modules.risk_policy.model import tier_for_mutation_class
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, field_validator

from cairn_api.routes_design import DesignRecord, DesignRegistry

CREATE_ROLES: tuple[Role, ...] = (
    Role.TENANT_ADMIN,
    Role.PROJECT_OWNER,
    Role.ARCHITECT,
    Role.ENGINEER,
)
"""Spec §12.1's ``ENGINEER`` row read as ``ENGINEER+`` -- the identical
tuple ``routes_transformations.CREATE_ROLES`` already defines for the
identical spec cell, not re-derived."""

READ_ROLES: tuple[Role, ...] = tuple(Role)
"""``VIEWER+`` -- any granted tenant role, same reasoning as
``routes_transformations.READ_ROLES``."""

DECISION_ROLES: tuple[Role, ...] = (*CREATE_ROLES, Role.REVIEWER)
"""``ENGINEER+`` plus ``Role.REVIEWER`` -- spec §12.1's own REVIEWER
capability row ("Approve/reject, accept exceptions") is this exact
action, same reasoning ``routes_transformations.REVIEW_ROLES`` already
names explicitly."""


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


class CompensationContractRequest(BaseModel):
    """The recovery plan (rollback or compensation contract, ADR-010)
    the proposer attaches to this mutation, as the approver's console
    must see it. Every field is this unit's own domain model's own
    non-blank requirement (``CompensationContract.__post_init__``) --
    enforced here as a real 422 at the request boundary rather than
    left to surface as an unhandled error from that dataclass's own
    (defense-in-depth) guard, the same discipline
    ``CreateReviewCommentRequest`` already uses in
    ``routes_transformations.py``."""

    model_config = ConfigDict(extra="forbid")

    strategy: RecoveryStrategy
    plan_ref: str
    preconditions: str
    authority: str
    evidence: str
    failure_handling: str

    @field_validator("plan_ref", "preconditions", "authority", "evidence", "failure_handling")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("every recovery plan field must be non-blank")
        return value

    def to_contract(self) -> CompensationContract:
        return CompensationContract(
            strategy=self.strategy,
            plan_ref=self.plan_ref,
            preconditions=self.preconditions,
            authority=self.authority,
            evidence=self.evidence,
            failure_handling=self.failure_handling,
        )


class CreatePlanApprovalRequest(BaseModel):
    """Propose one design's Terraform plan revision for approval: the
    mutation class it will execute under, and (optionally -- this is
    exactly the field the deliberate-break test omits) the recovery
    plan that mutation requires. Omitting ``compensation`` is a valid,
    honestly-represented proposal -- "no recovery plan recorded yet" --
    never silently defaulted to a complete one."""

    model_config = ConfigDict(extra="forbid")

    mutation_class: MutationClass
    compensation: CompensationContractRequest | None = None


class CreateApprovalDecisionRequest(BaseModel):
    """Mirrors ``routes_transformations.CreateReviewCommentRequest``
    exactly -- the same reused ``ReviewDecisionKind`` shape, the same
    "plain COMMENT by default" reasoning."""

    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecisionKind = ReviewDecisionKind.COMMENT
    body: str

    @field_validator("body")
    @classmethod
    def _body_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an approval comment must have a non-empty body")
        return value


@dataclass(frozen=True, slots=True)
class PlanApprovalRecord:
    """One Terraform plan revision registered for approval: 787's own
    immutable revision payload, the recovery plan (if any) the proposer
    attached, and the approver's own comment/decision thread."""

    tenant_id: str
    project_id: str
    payload: TerraformPlanRevisionPayload
    compensation: CompensationContract | None
    thread: PlanApprovalThread


class PlanApprovalRegistry:
    """In-memory, process-local index of plan revisions registered for
    approval, keyed by ``revision_id`` -- the same "real repository is
    elsewhere; this index only serves the reads this console's own
    routes need" simplification ``routes_transformations.
    TransformationRegistry``/``routes_design.DesignRegistry`` already
    make. This console unit introduces no new persistent store of its
    own; a plan revision and its recovery plan are proposed and
    reviewed entirely within one process's lifetime here, same as a
    transformation run's review thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, PlanApprovalRecord] = {}

    def put(self, record: PlanApprovalRecord) -> None:
        with self._lock:
            self._records[record.payload.revision_id] = record

    def get(self, revision_id: str) -> PlanApprovalRecord | None:
        return self._records.get(revision_id)

    def add_comment(self, revision_id: str, comment: ApprovalComment) -> PlanApprovalThread:
        with self._lock:
            existing = self._records.get(revision_id)
            if existing is None:
                raise NotFoundError(f"plan revision {revision_id} not found")
            thread = add_approval_comment(existing.thread, comment)
            self._records[revision_id] = dataclasses.replace(existing, thread=thread)
            return thread


def _diff_entry_to_jsonable(entry: Any) -> dict[str, Any]:
    return {
        "resource_id": entry.resource_id,
        "action": entry.action.value,
        "source_provider": entry.source_provider,
        "source_service": entry.source_service,
        "target_provider": entry.target_provider,
        "target_service": entry.target_service,
        "approximate": entry.approximate,
        "detail": entry.detail,
    }


def _compensation_summary(compensation: CompensationContract | None) -> dict[str, Any] | None:
    if compensation is None:
        return None
    return {
        "strategy": compensation.strategy.value,
        "plan_ref": compensation.plan_ref,
        "preconditions": compensation.preconditions,
        "authority": compensation.authority,
        "evidence": compensation.evidence,
        "failure_handling": compensation.failure_handling,
    }


_NO_RECOVERY_PLAN_RECORDED = (
    "No recovery plan has been recorded for this revision yet -- nothing is"
    " committed to capture, and this mutation cannot be approved from this"
    " console until one is."
)


def _approval_summary(thread: PlanApprovalThread) -> dict[str, Any]:
    return {
        "revision_id": thread.revision_id,
        "blocked": thread.blocked,
        "reviewed": thread.reviewed,
        "comments": [
            {
                "reviewer_actor_id": comment.reviewer_actor_id,
                "decision": comment.decision.value,
                "body": comment.body,
                "created_at": comment.created_at,
            }
            for comment in thread.comments
        ],
    }


def _approval_view(record: PlanApprovalRecord) -> dict[str, Any]:
    payload = record.payload
    tier = tier_for_mutation_class(payload.mutation_class)
    return {
        "revision": {
            "revision_id": payload.revision_id,
            "tenant_id": payload.tenant_id,
            "project_id": payload.project_id,
            "design_id": payload.design_id,
            "revision_number": payload.revision_number,
            "content_hash": payload.content_hash,
            "mutation_class": payload.mutation_class.value,
            "created_by": payload.created_by,
            "created_at": payload.created_at,
            "diff": [_diff_entry_to_jsonable(entry) for entry in payload.diff],
            "resource_list": list(payload.resource_list),
            "reversible": payload.reversible,
            "provider_preview": payload.provider_preview,
        },
        "risk_tier": tier.value if tier is not None else None,
        "recovery_plan": _compensation_summary(record.compensation),
        "evidence_to_capture": (
            record.compensation.evidence
            if record.compensation is not None
            else _NO_RECOVERY_PLAN_RECORDED
        ),
        "approval": _approval_summary(record.thread),
    }


def register_approval_console_routes(
    app: FastAPI,
    *,
    registry: PlanApprovalRegistry,
    design_registry: DesignRegistry,
    provider_port: ProviderExecutionPort | None = None,
    clock: Clock | None = None,
) -> None:
    """Register the 792/R4-05 approval-console routes directly on
    ``app`` (same convention as every other route module -- see
    ``routes_projects.register_projects_routes`` for why).

    ``provider_port`` defaults to ``FakeProviderExecutionAdapter`` --
    this unit is explicitly "no cloud"; a caller can inject a different
    fake for its own tests, but never a real provider adapter from this
    module's own default.
    """

    router = app
    resolved_provider_port = provider_port or FakeProviderExecutionAdapter()
    resolved_clock = clock or SystemClock()

    def _load_design(design_id: str, principal: Principal) -> DesignRecord:
        record = design_registry.get_design(design_id)
        if record is None or record.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"design {design_id} not found")
        return record

    def _load_record(revision_id: str, principal: Principal) -> PlanApprovalRecord:
        record = registry.get(revision_id)
        if record is None or record.tenant_id != principal.tenant_id.value:
            raise NotFoundError(f"plan revision {revision_id} not found")
        return record

    @router.post("/v1/designs/{design_id}/approval")
    def create_plan_approval(
        design_id: str,
        payload: CreatePlanApprovalRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, Any]:
        require_roles(principal, *CREATE_ROLES)
        design = _load_design(design_id, principal)

        revision_payload = orchestrate_terraform_plan(
            plan_artefact=design.iac,
            provider_port=resolved_provider_port,
            mutation_class=payload.mutation_class,
            created_by=principal.subject,
            clock=resolved_clock,
        )
        compensation = payload.compensation.to_contract() if payload.compensation else None
        record = PlanApprovalRecord(
            tenant_id=principal.tenant_id.value,
            project_id=design.project_id,
            payload=revision_payload,
            compensation=compensation,
            thread=PlanApprovalThread(revision_id=revision_payload.revision_id),
        )
        registry.put(record)
        return jsonable_encoder(_approval_view(record))

    @router.get("/v1/plans/{revision_id}/approval")
    def get_plan_approval(
        revision_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, Any]:
        require_roles(principal, *READ_ROLES)
        record = _load_record(revision_id, principal)
        return jsonable_encoder(_approval_view(record))

    @router.post("/v1/plans/{revision_id}/approval-comments")
    def create_approval_decision(
        revision_id: str,
        payload: CreateApprovalDecisionRequest,
        principal: Principal = Depends(get_principal),
    ) -> dict[str, Any]:
        require_roles(principal, *DECISION_ROLES)
        record = _load_record(revision_id, principal)

        if payload.decision is ReviewDecisionKind.APPROVE:
            # 783's own gate, re-enforced at this console's own layer --
            # raises (fails closed, no comment recorded) when the
            # recovery plan is missing or mismatched. See this module's
            # own docstring.
            ensure_recovery_plan_complete(record.payload.mutation_class, record.compensation)

        comment = ApprovalComment(
            revision_id=revision_id,
            reviewer_actor_id=principal.subject,
            decision=payload.decision,
            body=payload.body,
            created_at=datetime.now(UTC),
        )
        thread = registry.add_comment(revision_id, comment)
        return jsonable_encoder(_approval_summary(thread))

    @router.get("/v1/plans/{revision_id}/approval-comments")
    def list_approval_decisions(
        revision_id: str, principal: Principal = Depends(get_principal)
    ) -> dict[str, Any]:
        require_roles(principal, *READ_ROLES)
        record = _load_record(revision_id, principal)
        return jsonable_encoder(_approval_summary(record.thread))


__all__ = [
    "CREATE_ROLES",
    "DECISION_ROLES",
    "READ_ROLES",
    "CompensationContractRequest",
    "CreateApprovalDecisionRequest",
    "CreatePlanApprovalRequest",
    "PlanApprovalRecord",
    "PlanApprovalRegistry",
    "get_principal",
    "register_approval_console_routes",
]
