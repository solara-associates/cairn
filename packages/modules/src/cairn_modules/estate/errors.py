"""Errors raised by canonical estate normalization."""

from __future__ import annotations

from cairn_kernel.errors import ValidationError


class UnsupportedSourceFormatError(ValidationError):
    """Raised for a ``RawObservation.source_format`` with no known mapping.

    Normalization fails closed rather than guessing a mapping for a format
    it does not recognize.
    """

    title = "Unsupported ingestion source format"


class MissingIdentityError(ValidationError):
    """Raised when a raw observation has no value for its identity field.

    Without an identity, the observation cannot be attributed to a stable
    resource -- normalization must not fabricate one.
    """

    title = "Observation is missing its identity field"


__all__ = ["MissingIdentityError", "UnsupportedSourceFormatError"]
