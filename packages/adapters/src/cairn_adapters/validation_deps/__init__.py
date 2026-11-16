"""R3-05: the "dependency" half of ``ValidationPort`` (spec §5.4) --
checks that the proposed change does not introduce a dependency the
source repository's own manifest does not already declare (Python
``requirements.txt``/``pyproject.toml`` packages, Terraform ``module``
sources), never a live package-index lookup. Plus a deterministic fake
for tests."""

from cairn_adapters.validation_deps.fake import FakeDependencyValidationAdapter
from cairn_adapters.validation_deps.real import (
    DEPENDENCY_CHECK_ID,
    DependencyValidationAdapter,
)

__all__ = [
    "DEPENDENCY_CHECK_ID",
    "DependencyValidationAdapter",
    "FakeDependencyValidationAdapter",
]
