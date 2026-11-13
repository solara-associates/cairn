"""CAIRN cairn_modules.estate: R1-06 canonical estate normalization.

Maps R1-03's common raw-observation shape into ``contracts/estate``'s
canonical ``Resource`` entities, with provenance on every field and
conflicting observations preserved rather than collapsed (ADR-003).
"""

from cairn_modules.estate.errors import MissingIdentityError, UnsupportedSourceFormatError
from cairn_modules.estate.mapping import SourceMapping, source_mapping, supported_source_formats
from cairn_modules.estate.normalize import CONFLICT_SEPARATOR, UNVERIFIED, conflicts, normalize

__all__ = [
    "CONFLICT_SEPARATOR",
    "UNVERIFIED",
    "MissingIdentityError",
    "SourceMapping",
    "UnsupportedSourceFormatError",
    "conflicts",
    "normalize",
    "source_mapping",
    "supported_source_formats",
]
