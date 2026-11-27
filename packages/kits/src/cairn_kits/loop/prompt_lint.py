"""R6-01: the A6.prompts mechanical check.

A6.prompts requires that no prompt literal above a length threshold
reaches a model call; prompts are versioned files resolved by id
through ``PromptRegistry`` instead. This walks the given source roots
and flags any call-site keyword argument named ``prompt`` whose value
is a string literal longer than the threshold -- the shape a hand-typed
prompt string takes at a ``ModelRequest(prompt=...)`` or
``ModelPort.generate(prompt=...)`` call site.

This is advisory scanning, not a security boundary: it catches the
literal-string shape the rule is about, not every way a string could
be assembled and handed to the same keyword.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 120


@dataclass(frozen=True, slots=True)
class PromptLiteralViolation:
    path: Path
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


def find_prompt_literal_violations(
    roots: Sequence[Path], threshold: int = DEFAULT_THRESHOLD
) -> list[PromptLiteralViolation]:
    violations: list[PromptLiteralViolation] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "prompt":
                        continue
                    value = keyword.value
                    if (
                        isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and len(value.value) > threshold
                    ):
                        violations.append(PromptLiteralViolation(path=path, line=node.lineno))
    return violations


__all__ = ["DEFAULT_THRESHOLD", "PromptLiteralViolation", "find_prompt_literal_violations"]
