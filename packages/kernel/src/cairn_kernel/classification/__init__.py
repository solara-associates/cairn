"""CAIRN cairn_kernel.classification.

The operation classification matrix for story R0-19: every API, MCP tool/
resource, event and worker job that exists today carries exactly one entry
here. The matrix is the contract; ``tests/conformance/
test_classification_matrix.py`` discovers the real surfaces in the codebase
and fails if one is missing from it.

Table and bucket entity tenancy classification is not duplicated here — see
``cairn_kernel.tenancy.classification``.
"""

from cairn_kernel.classification.matrix import OPERATIONS
from cairn_kernel.classification.model import (
    CompensationContract,
    OperationEntry,
    RecoveryStrategy,
    SurfaceKind,
    operations_by_name,
    require_classified,
)

__all__ = [
    "OPERATIONS",
    "CompensationContract",
    "OperationEntry",
    "RecoveryStrategy",
    "SurfaceKind",
    "operations_by_name",
    "require_classified",
]
