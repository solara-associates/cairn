"""R3-01: file-extension language detection shared by the Git and upload
adapters.

ADR-015 scopes this release's transformation engine to Terraform/HCL and
Python. A file outside that scope is still returned as a ``SourceFile``
(ADR-010/spec §16: nothing a fetch reads is ever silently dropped) --
it is simply labelled ``UNSUPPORTED`` rather than carrying a detected
language.
"""

from __future__ import annotations

from cairn_contracts.transformation import SourceLanguage

_TERRAFORM_SUFFIXES = (".tf", ".tf.json", ".hcl")
_PYTHON_SUFFIXES = (".py",)


def detect_language(path: str) -> SourceLanguage:
    lowered = path.lower()
    if lowered.endswith(_TERRAFORM_SUFFIXES):
        return SourceLanguage.TERRAFORM
    if lowered.endswith(_PYTHON_SUFFIXES):
        return SourceLanguage.PYTHON
    return SourceLanguage.UNSUPPORTED


__all__ = ["detect_language"]
