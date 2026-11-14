"""Tests for R1-10 posture assessment and coverage reporting.

Covers the acceptance criterion: "Deterministic scoring only where rules
support; unknown visible."

- deterministic scoring: the same findings in, the same score out, every
  run, for an automated control;
- unknown-visibility: a manual control (no automated rule logic), and an
  automated control with no findings, are both explicitly UNKNOWN, never
  defaulted to a pass;
- coverage reporting: which controls were evaluated vs. not is a
  first-class, independently checkable output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_contracts.posture import ControlVersionReference
from cairn_modules.posture import (
    ControlScoreStatus,
    Finding,
    FindingStatus,
    assess,
    load_control_catalogue_release,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = REPO_ROOT / "controls" / "gcp-cis-seed.yaml"
MOMENT = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


def _release():
    return load_control_catalogue_release(SEED_PATH)


def _finding(control_id: str, release_version: str, status: FindingStatus, resource_id: str) -> Finding:
    return Finding(
        scanner="prowler",
        scanner_check_id=f"check-{control_id}",
        control_reference=ControlVersionReference(control_id=control_id, release_version=release_version),
        status=status,
        resource_id=resource_id,
        resource_type="project",
        message="",
        observed_at=MOMENT,
    )


# --- deterministic scoring ---------------------------------------------------


def test_automated_control_with_only_passing_findings_scores_pass_deterministically() -> None:
    release = _release()
    findings = [
        _finding("gcp-cis-1.1", release.version, FindingStatus.PASS, "proj-a"),
        _finding("gcp-cis-1.1", release.version, FindingStatus.PASS, "proj-b"),
    ]

    first = assess(release, findings)
    second = assess(release, findings)

    assert first.score_for("gcp-cis-1.1").status is ControlScoreStatus.PASS
    assert first.score_for("gcp-cis-1.1") == second.score_for("gcp-cis-1.1")


def test_any_failing_finding_fails_the_control() -> None:
    release = _release()
    findings = [
        _finding("gcp-cis-1.1", release.version, FindingStatus.PASS, "proj-a"),
        _finding("gcp-cis-1.1", release.version, FindingStatus.FAIL, "proj-b"),
    ]

    result = assess(release, findings)

    assert result.score_for("gcp-cis-1.1").status is ControlScoreStatus.FAIL
    assert result.score_for("gcp-cis-1.1").finding_count == 2


def test_scoring_ignores_findings_from_a_different_release_version() -> None:
    release = _release()
    findings = [_finding("gcp-cis-1.1", "2099.01.1", FindingStatus.FAIL, "proj-a")]

    result = assess(release, findings)

    score = result.score_for("gcp-cis-1.1")
    assert score.status is ControlScoreStatus.UNKNOWN
    assert score.evaluated is False
    assert score.finding_count == 0


# --- unknown is visible, never defaulted -------------------------------------


def test_manual_control_is_always_unknown_even_with_matching_findings() -> None:
    """gcp-cis-2.1 is the seed's one manual (automated: false) control."""
    release = _release()
    manual_control = next(c for c in release.controls if not c.automated)
    assert manual_control.id == "gcp-cis-2.1"

    # Even if a finding somehow references it, no automated rule logic
    # exists to turn that into a deterministic PASS/FAIL.
    findings = [_finding(manual_control.id, release.version, FindingStatus.PASS, "proj-a")]
    result = assess(release, findings)

    score = result.score_for(manual_control.id)
    assert score.status is ControlScoreStatus.UNKNOWN
    assert "manual" in score.reason


def test_automated_control_with_no_findings_is_unknown_not_a_default_pass() -> None:
    release = _release()
    result = assess(release, findings=())

    for score in result.scores:
        assert score.status is ControlScoreStatus.UNKNOWN
        assert score.evaluated is False


def test_unresolved_finding_keeps_control_unknown_unless_something_already_failed() -> None:
    release = _release()
    findings = [
        _finding("gcp-cis-1.1", release.version, FindingStatus.PASS, "proj-a"),
        _finding("gcp-cis-1.1", release.version, FindingStatus.UNKNOWN, "proj-b"),
    ]

    result = assess(release, findings)

    assert result.score_for("gcp-cis-1.1").status is ControlScoreStatus.UNKNOWN


# --- coverage reporting -------------------------------------------------------


def test_coverage_report_separates_evaluated_from_not_evaluated() -> None:
    release = _release()
    findings = [
        _finding("gcp-cis-1.1", release.version, FindingStatus.PASS, "proj-a"),
        _finding("gcp-cis-3.6", release.version, FindingStatus.FAIL, "proj-a"),
    ]

    result = assess(release, findings)

    assert result.coverage.evaluated_control_ids == ("gcp-cis-1.1", "gcp-cis-3.6")
    all_ids = {control.id for control in release.controls}
    assert set(result.coverage.not_evaluated_control_ids) == all_ids - {"gcp-cis-1.1", "gcp-cis-3.6"}
    assert result.coverage.total_controls == len(release.controls)


def test_manual_control_evaluated_by_a_real_finding_still_counts_as_evaluated() -> None:
    """Coverage ('was it looked at') is independent of scorability
    ('can a verdict be computed') -- a manual control that does get a
    finding attached is still reported as evaluated, even though its
    score stays UNKNOWN.
    """
    release = _release()
    manual_control = next(c for c in release.controls if not c.automated)
    findings = [_finding(manual_control.id, release.version, FindingStatus.PASS, "proj-a")]

    result = assess(release, findings)

    assert manual_control.id in result.coverage.evaluated_control_ids
    assert result.score_for(manual_control.id).status is ControlScoreStatus.UNKNOWN
