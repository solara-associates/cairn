"""R6-12: resolving a narrative's ``fact_ref`` against the assessment
run it claims to describe.

Design §3.1's validation rule 3 is "every explanation and every anomaly
cites at least one ``fact_ref`` that resolves to a real fact in the run
(an estate fact, a posture finding, a cost line). An uncited claim is
rejected." That needs a reference scheme, and this module is it: four
shapes, each resolving against an artifact the run's own stages already
wrote (``cairn_modules.assessment.stages``), and nothing invented.

| Reference | Resolves against | Status taken from |
|---|---|---|
| ``workload:<workload_id>/<fact_key>`` | ``workloads`` | ``FactValue.status`` |
| ``resource:<resource_id>/<fact_key>`` | ``resources`` | ``FactValue.status`` |
| ``control:<control_id>`` | ``posture_assessment.scores`` | see below |
| ``cost:<cost_id>`` | ``cost_records`` | ``OBSERVED`` |

A reference that does not resolve is not a weak citation, it is no
citation: ``resolve_fact_ref`` raises, and the narrative carrying it is
rejected before anything is persisted.

**Status for the two artifacts that carry no ``FactStatus`` of their
own.** A ``ControlScore`` that was not evaluated is ``UNAVAILABLE`` and
one scored ``UNKNOWN`` is ``UNVERIFIED`` -- both are "we did not
establish this", which is exactly what those two ``FactStatus`` values
mean, and neither may be reproduced as an established fact. A scored
``PASS``/``FAIL`` and a ``CostRecord`` are both recorded observations
carrying provenance, so both are ``OBSERVED``. This mapping is declared
here, once, rather than inferred per caller.

**No text parsing.** R-MAP-01 is enforced on these statuses, never by
reading an explanation's prose for words like "exactly" --
``cairn_modules.design.diagram`` already set that precedent for this
codebase ("it never parses the resolver's free-text reason/caveat
strings to recover a distinction those types don't structurally
carry"), and a rule that depends on spotting a synonym is a rule a
model can get past by rewording.
"""

from __future__ import annotations

from cairn_contracts.estate import CostRecord, FactStatus, Resource, Workload
from cairn_kernel.errors import ValidationError

from cairn_modules.assessment import AssessmentRun
from cairn_modules.posture.assessment import ControlScore, ControlScoreStatus, PostureAssessment

WORKLOAD_PREFIX = "workload:"
RESOURCE_PREFIX = "resource:"
CONTROL_PREFIX = "control:"
COST_PREFIX = "cost:"

#: The statuses a narrative may never reproduce as an established fact
#: (design §3.1 rule 4, R-MAP-01). ``UNVERIFIED`` is in here with the
#: other two deliberately: "nobody checked" is as far from exact as
#: "approximately" is, and a reader shown it as fact is misled either
#: way.
NOT_EXACT_STATUSES: frozenset[FactStatus] = frozenset(
    {FactStatus.APPROXIMATE, FactStatus.UNAVAILABLE, FactStatus.UNVERIFIED}
)


def _split_keyed(ref: str, prefix: str) -> tuple[str, str]:
    body = ref[len(prefix) :]
    subject_id, separator, fact_key = body.partition("/")
    if not separator or not subject_id or not fact_key:
        raise ValidationError(f"fact reference {ref!r} must be {prefix}<id>/<fact_key>")
    return subject_id, fact_key


def _fact_status(
    subject_id: str, fact_key: str, facts: dict[str, object], *, ref: str, kind: str
) -> FactStatus:
    value = facts.get(fact_key)
    if value is None:
        raise ValidationError(
            f"fact reference {ref!r} names no fact {fact_key!r} on {kind} {subject_id!r}"
        )
    return value.status  # type: ignore[attr-defined]


def _control_status(score: ControlScore) -> FactStatus:
    if not score.evaluated:
        return FactStatus.UNAVAILABLE
    if score.status is ControlScoreStatus.UNKNOWN:
        return FactStatus.UNVERIFIED
    return FactStatus.OBSERVED


def resolve_fact_ref(ref: str, run: AssessmentRun) -> FactStatus:
    """The status of the fact ``ref`` names within ``run``.

    Raises ``ValidationError`` if ``ref`` is malformed, names an unknown
    reference kind, or resolves to nothing in this run's artifacts --
    an unresolvable citation is no citation.
    """

    artifacts = run.context.artifacts

    if ref.startswith(WORKLOAD_PREFIX):
        workload_id, fact_key = _split_keyed(ref, WORKLOAD_PREFIX)
        workloads: tuple[Workload, ...] = artifacts.get("workloads", ())
        for workload in workloads:
            if workload.workload_id == workload_id:
                return _fact_status(
                    workload_id, fact_key, dict(workload.facts), ref=ref, kind="workload"
                )
        raise ValidationError(f"fact reference {ref!r} names no workload in run {run.run_id}")

    if ref.startswith(RESOURCE_PREFIX):
        resource_id, fact_key = _split_keyed(ref, RESOURCE_PREFIX)
        resources: tuple[Resource, ...] = artifacts.get("resources", ())
        for resource in resources:
            if resource.resource_id == resource_id:
                return _fact_status(
                    resource_id, fact_key, dict(resource.facts), ref=ref, kind="resource"
                )
        raise ValidationError(f"fact reference {ref!r} names no resource in run {run.run_id}")

    if ref.startswith(CONTROL_PREFIX):
        control_id = ref[len(CONTROL_PREFIX) :]
        posture: PostureAssessment | None = artifacts.get("posture_assessment")
        if posture is None:
            raise ValidationError(
                f"fact reference {ref!r} cites a control, but run {run.run_id} has no"
                " posture assessment"
            )
        for score in posture.scores:
            if score.control_id == control_id:
                return _control_status(score)
        raise ValidationError(f"fact reference {ref!r} names no scored control in run {run.run_id}")

    if ref.startswith(COST_PREFIX):
        cost_id = ref[len(COST_PREFIX) :]
        cost_records: tuple[CostRecord, ...] = artifacts.get("cost_records", ())
        for record in cost_records:
            if record.cost_id == cost_id:
                return FactStatus.OBSERVED
        raise ValidationError(f"fact reference {ref!r} names no cost line in run {run.run_id}")

    raise ValidationError(
        f"fact reference {ref!r} names no known reference kind; expected one of "
        f"{sorted((WORKLOAD_PREFIX, RESOURCE_PREFIX, CONTROL_PREFIX, COST_PREFIX))}"
    )


def not_exact_refs(refs: tuple[str, ...], run: AssessmentRun) -> tuple[str, ...]:
    """Every reference in ``refs`` whose fact is not an established one,
    in the order given -- the set a narrative must reproduce rather than
    quietly drop (design §3.1 rule 4)."""

    return tuple(ref for ref in refs if resolve_fact_ref(ref, run) in NOT_EXACT_STATUSES)


__all__ = [
    "CONTROL_PREFIX",
    "COST_PREFIX",
    "NOT_EXACT_STATUSES",
    "RESOURCE_PREFIX",
    "WORKLOAD_PREFIX",
    "not_exact_refs",
    "resolve_fact_ref",
]
