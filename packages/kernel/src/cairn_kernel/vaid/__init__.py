"""CAIRN cairn_kernel.vaid: VAID verification, in core (ADR-020 §3).

See ``verification.py``'s own docstring for what is verified, what is
deliberately not, and what CAIRN requires of an issuer minting VAIDs
for it.
"""

from cairn_kernel.vaid.selection import ENV_VAID_ENABLED, resolve_vaid_authenticator
from cairn_kernel.vaid.trust import (
    ENV_VAID_KERNEL_KEYS,
    ENV_VAID_TRUST_DOMAINS,
    VaidTrustAnchors,
)
from cairn_kernel.vaid.verification import (
    VAID_SUBJECT_PREFIX,
    VaidAuthenticator,
    VaidPresentation,
    VaidScope,
    VaidScopeWideningError,
    VaidVerificationError,
    VerifiedVaid,
)

__all__ = [
    "ENV_VAID_ENABLED",
    "ENV_VAID_KERNEL_KEYS",
    "ENV_VAID_TRUST_DOMAINS",
    "VAID_SUBJECT_PREFIX",
    "VaidAuthenticator",
    "VaidPresentation",
    "VaidScope",
    "VaidScopeWideningError",
    "VaidTrustAnchors",
    "VaidVerificationError",
    "VerifiedVaid",
    "resolve_vaid_authenticator",
]
