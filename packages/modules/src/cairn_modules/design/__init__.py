"""CAIRN cairn_modules.design."""

from cairn_modules.design.patterns import (
    InMemoryPatternRepository,
    load_pattern,
    load_pattern_catalogue,
)
from cairn_modules.design.revisions import (
    DESIGN_SUBJECT_KIND,
    DesignRevisionRepository,
    FakeDesignRevisionRepository,
    PostgresDesignRevisionRepository,
)
from cairn_modules.design.target_model import (
    TargetModel,
    TargetResourceEntry,
    TargetResourceStatus,
    generate_target_model,
)

__all__ = [
    "DESIGN_SUBJECT_KIND",
    "DesignRevisionRepository",
    "FakeDesignRevisionRepository",
    "InMemoryPatternRepository",
    "PostgresDesignRevisionRepository",
    "TargetModel",
    "TargetResourceEntry",
    "TargetResourceStatus",
    "generate_target_model",
    "load_pattern",
    "load_pattern_catalogue",
]
