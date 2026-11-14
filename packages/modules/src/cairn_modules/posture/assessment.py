"""R1-10: posture assessment and coverage reporting.

Scores R1-08 control catalogue controls against R1-09's normalized
``Finding``\\ s. A deterministic verdict (``PASS``/``FAIL``) is produced
only where a control's own rule logic actually supports one:

- A manual control (``ControlDefinition.automated is False``) has no
  automated rule logic at all -- its score is always explicitly
  ``UNKNOWN``, never defaulted to a pass just because no failure was
  reported.
- An automated control with no findings at all was never evaluated --
  also ``UNKNOWN``, not assumed to have passed.
- An automated control with findings whose own verdict is itself
  ``UNKNOWN`` (the scanner couldn't determine a result) keeps the
  control's score ``UNKNOWN`` unless another finding already fails it --
  an unresolved finding is never silently treated as a pass.

Coverage -- which controls were evaluated at all, independent of what
their score came out to be -- is reported as a first-class output
(:class:`CoverageReport`), not folded into the score.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from cairn_contracts.posture import ControlCatalogueRelease, ControlDefinition

from cairn_modules.posture.findings import Finding, FindingStatus


class ControlScoreStatus(str, Enum):
    """A control's posture verdict for one assessment."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ControlScore:
    """One control's score within one assessment."""

    control_id: str
    release_version: str
    status: ControlScoreStatus
    evaluated: bool
    finding_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Which controls in a release were evaluated at all, and which weren't."""

    release_version: str
    evaluated_control_ids: tuple[str, ...]
    not_evaluated_control_ids: tuple[str, ...]

    @property
    def total_controls(self) -> int:
        return len(self.evaluated_control_ids) + len(self.not_evaluated_control_ids)


@dataclass(frozen=True, slots=True)
class PostureAssessment:
    """The full result of scoring one control catalogue release."""

    release_version: str
    scores: tuple[ControlScore, ...]
    coverage: CoverageReport

    def score_for(self, control_id: str) -> ControlScore:
        for score in self.scores:
            if score.control_id == control_id:
                return score
        raise KeyError(control_id)


def _score_control(
    control: ControlDefinition,
    release_version: str,
    findings: Sequence[Finding],
) -> ControlScore:
    if not control.automated:
        return ControlScore(
            control_id=control.id,
            release_version=release_version,
            status=ControlScoreStatus.UNKNOWN,
            evaluated=bool(findings),
            finding_count=len(findings),
            reason="manual control -- no automated rule logic supports a verdict",
        )

    if not findings:
        return ControlScore(
            control_id=control.id,
            release_version=release_version,
            status=ControlScoreStatus.UNKNOWN,
            evaluated=False,
            finding_count=0,
            reason="no findings evaluated this control in this release",
        )

    statuses = {finding.status for finding in findings}
    if FindingStatus.FAIL in statuses:
        status = ControlScoreStatus.FAIL
        reason = "at least one finding failed"
    elif FindingStatus.UNKNOWN in statuses:
        status = ControlScoreStatus.UNKNOWN
        reason = "no failures observed, but at least one finding's own verdict is unknown"
    else:
        status = ControlScoreStatus.PASS
        reason = "every finding passed"

    return ControlScore(
        control_id=control.id,
        release_version=release_version,
        status=status,
        evaluated=True,
        finding_count=len(findings),
        reason=reason,
    )


def assess(release: ControlCatalogueRelease, findings: Sequence[Finding]) -> PostureAssessment:
    """Score every control in ``release`` against ``findings``.

    Only findings whose ``control_reference.release_version`` matches
    ``release.version`` are considered -- a finding evaluated against a
    different release of a control does not count toward this one.
    """
    by_control: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if finding.control_reference.release_version != release.version:
            continue
        by_control[finding.control_reference.control_id].append(finding)

    scores = tuple(
        _score_control(control, release.version, tuple(by_control.get(control.id, ())))
        for control in release.controls
    )

    coverage = CoverageReport(
        release_version=release.version,
        evaluated_control_ids=tuple(sorted(score.control_id for score in scores if score.evaluated)),
        not_evaluated_control_ids=tuple(
            sorted(score.control_id for score in scores if not score.evaluated)
        ),
    )

    return PostureAssessment(release_version=release.version, scores=scores, coverage=coverage)


__all__ = [
    "ControlScore",
    "ControlScoreStatus",
    "CoverageReport",
    "PostureAssessment",
    "assess",
]
