"""CAIRN cairn_modules.reporting.

R1-16: human-readable report rendering for a completed (or incomplete)
R1-15 assessment run.

R2-08: machine-readable (JSON) export bundle and human-readable report
for a design's export set (target model, diagram, plan/roadmap, IaC
preview) -- reusing R1-16's reporting discipline rather than inventing a
new report format.
"""

from cairn_modules.reporting.design_export import (
    DesignExportBundle,
    DesignRevisionSection,
    DiagramSection,
    IacSection,
    PlanSection,
    VersionStamp,
    build_design_export_bundle,
)
from cairn_modules.reporting.design_report import (
    DesignReport,
    DesignReportAssumptions,
    DesignReportCoverage,
    DesignReportIac,
    DesignReportPlan,
    DesignReportVersions,
    render_design_report,
)
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
    "DesignExportBundle",
    "DesignReport",
    "DesignReportAssumptions",
    "DesignReportCoverage",
    "DesignReportIac",
    "DesignReportPlan",
    "DesignReportVersions",
    "DesignRevisionSection",
    "DiagramSection",
    "IacSection",
    "PlanSection",
    "PostureCoverage",
    "RunCoverage",
    "TcoAssumptionsSection",
    "VersionStamp",
    "VersionsSection",
    "build_design_export_bundle",
    "render_design_report",
    "render_report",
    "with_evidence_package_hash",
]
