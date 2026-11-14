"""CAIRN cairn_modules.reporting.

R1-16: human-readable report rendering for a completed (or incomplete)
R1-15 assessment run.
"""

from cairn_modules.reporting.renderer import (
    AssessmentReport,
    CostCoverage,
    PostureCoverage,
    RunCoverage,
    TcoAssumptionsSection,
    VersionsSection,
    render_report,
    with_evidence_package_hash,
)

__all__ = [
    "AssessmentReport",
    "CostCoverage",
    "PostureCoverage",
    "RunCoverage",
    "TcoAssumptionsSection",
    "VersionsSection",
    "render_report",
    "with_evidence_package_hash",
]
