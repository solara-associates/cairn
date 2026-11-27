"""ADR-020 §3: whether this deployment accepts VAIDs at all.

The same shape ``cairn_adapters.model.selection.resolve_model_adapter``
already established for ``ModelPort``: one env var decides, the default
is the one a clean clone and ``make test`` get, and selecting the real
thing with its configuration missing fails here, at startup, not at the
first credential a running gateway is shown.

The default is **off**: ``resolve_vaid_authenticator`` returns ``None``,
the gateway binds no VAID authenticator, and a caller presenting a VAID
is refused because this deployment pinned no trust anchor to check it
against. Callers presenting a bearer token are entirely unaffected --
that is ADR-020 §3's "callers without a VAID keep today's
authentication", and it is the default rather than a special case.
"""

from __future__ import annotations

import os

from vaid_mint import RevocationCheck

from cairn_kernel.errors import ConfigurationError
from cairn_kernel.vaid.trust import VaidTrustAnchors
from cairn_kernel.vaid.verification import VaidAuthenticator

ENV_VAID_ENABLED = "CAIRN_VAID_ENABLED"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})


def resolve_vaid_authenticator(
    revocation: RevocationCheck,
    env: dict[str, str] | None = None,
) -> VaidAuthenticator | None:
    """Build the :class:`VaidAuthenticator` this deployment accepts VAIDs
    with, or ``None`` when it accepts none.

    ``CAIRN_VAID_ENABLED`` unset (or any of ``0``/``false``/``no``/``off``)
    resolves to ``None``. Enabling it builds the authenticator from
    :meth:`VaidTrustAnchors.from_env`, which itself raises
    ``ConfigurationError`` if the kernel keys or accepted trust domains
    are missing -- enabled-but-unconfigured is a startup failure, never
    an authenticator with nothing pinned. Any other value is rejected
    outright, the same fail-loudly shape.

    ``revocation`` is the caller's own choice of revocation source and
    has no default here either, for the reason
    :class:`VaidAuthenticator` documents.
    """

    source = env if env is not None else os.environ
    raw = source.get(ENV_VAID_ENABLED, "").strip().lower()
    if raw in _FALSE_VALUES:
        return None
    if raw not in _TRUE_VALUES:
        raise ConfigurationError(
            f"{ENV_VAID_ENABLED}={raw!r} is not a recognised boolean "
            f"(expected one of {sorted(_TRUE_VALUES | _FALSE_VALUES - {''})})"
        )
    return VaidAuthenticator(VaidTrustAnchors.from_env(dict(source)), revocation)


__all__ = ["ENV_VAID_ENABLED", "resolve_vaid_authenticator"]
