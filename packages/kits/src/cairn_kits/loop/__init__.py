"""CAIRN cairn_kits.loop: the agent loop kit (ADR-019).

R6-01 adds the prompt registry; later R6 units add the loop contract,
budgets and the propose-only tool-capability boundary in this same
package.
"""

from cairn_kits.loop.prompt_lint import (
    DEFAULT_THRESHOLD,
    PromptLiteralViolation,
    find_prompt_literal_violations,
)
from cairn_kits.loop.prompt_registry import PromptArtifact, PromptRegistry

__all__ = [
    "DEFAULT_THRESHOLD",
    "PromptArtifact",
    "PromptLiteralViolation",
    "PromptRegistry",
    "find_prompt_literal_violations",
]
