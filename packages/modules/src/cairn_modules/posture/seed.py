from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import ValidationError
from pydantic import ValidationError as PydanticValidationError


def load_control_catalogue_release(path: Path | str) -> ControlCatalogueRelease:
    release_path = Path(path)
    try:
        raw = release_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(
            f"cannot read control catalogue release {release_path}: {exc}"
        ) from exc

    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValidationError(
            f"invalid YAML in control catalogue release {release_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValidationError(
            f"control catalogue release {release_path} must be a YAML mapping"
        )

    try:
        return ControlCatalogueRelease.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"invalid control catalogue release {release_path}: {exc}"
        ) from exc


__all__ = ["load_control_catalogue_release"]
