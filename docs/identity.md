# Identity and sign-in

CAIRN ships **no hosted identity provider**. Every deployment -- local,
self-hosted, or a maintainer's own hosted service -- brings its own
OpenID Connect (OIDC) provider. The console and API only ever speak a
provider-agnostic authorization-code flow with PKCE (RFC 7636); nothing
in the code is specific to any one identity provider.

## How it works

- `apps/console/src/oidc.ts` drives the browser-side flow: discovery,
  PKCE challenge/verifier, the redirect, the callback token exchange,
  and token refresh. It never talks to anything but the generic
  endpoints a spec-compliant OIDC provider publishes.
- `cairn_adapters.auth_oidc.JwtAuthenticator` verifies the resulting
  token server-side: issuer, audience, signature (via JWKS or a shared
  secret), and maps configured claims to a tenant ID and roles.
- Configuration is runtime, not baked into the build: the console reads
  `/config.json` (generated from `CAIRN_CONSOLE_OIDC_*` environment
  variables at container start -- see
  `apps/console/docker-entrypoint.sh`); the API reads `CAIRN_OIDC_*`
  environment variables, including which claims carry the tenant ID and
  roles (`CAIRN_OIDC_TENANT_CLAIM`, `CAIRN_OIDC_ROLES_CLAIM` -- see
  `apps/api/src/cairn_api/app.py`). The same built image works against
  whichever provider a deployment points it at.
- Until these are set, the API fails closed: no token is accepted
  (`_ClosedAuthenticator` in `apps/api/src/cairn_api/app.py`).

## Local development: bundled dex

`docker compose up` starts a [`dex`](https://dexidp.io/) instance
(`infra/dex/config.yaml`) alongside the console and API, so you can sign
in without standing up a real identity provider first. This is the same
engine CAIRN's own OIDC integration is tested against end to end --
including RBAC role mapping, tenant isolation, token refresh, and
wrong-issuer rejection -- in
`apps/api/tests/test_oidc_dex_integration.py`.

For a one-click local sign-in with no password prompt, this dex instance
uses the `authproxy` connector, which trusts whoever sits in front of it
to have already authenticated the caller and to assert the identity via
headers. In this quickstart, the console's own nginx
(`infra/dex/console-dev.nginx.conf`, mounted over the console's default
config only by `compose.yaml`, not part of the built image) plays that
role: it proxies `/dex/*` to the dex container and unconditionally
asserts one fixed local demo identity
(`demo@cairn.local`, tenant `6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a`,
roles `VIEWER`+`ENGINEER`). Signing in gives you that identity --
nothing more, nothing less, and the same one every time.

This arrangement only makes sense for a single developer's own machine.
A real deployment does not run an unconditionally-trusting proxy in
front of its identity provider -- see "Deployments" below.

The console and dex share one origin (`http://localhost:3000`, proxied)
so the browser's OIDC discovery and token calls need no CORS headers;
dex does not send any. The API container reaches dex directly over the
compose network (`http://dex:5556/dex/keys`) for its own JWKS fetch,
which is server-to-server and unaffected by CORS either way.

## Deployments: bring your own OIDC

For anything beyond local exploration, point `CAIRN_OIDC_*` and
`CAIRN_CONSOLE_OIDC_*` at a real OIDC provider: your organisation's own
IdP, a customer's IdP (customer-SSO-only, so CAIRN never stores
end-user credentials), or a self-hosted provider you operate yourself
(dex or Keycloak, run as a real service with a real connector --
LDAP, SAML, or an upstream OIDC provider -- not the quickstart's
always-trusting proxy).

Before choosing, check your residency requirements against the
provider's own data-location options. As one example:
`docs/residency/uk-residency-matrix.md` records that Google Identity
Platform/Firebase Auth has no region-pinning for user-account data,
which made it unsuitable for a UK-only residency commitment, and
self-hosted OIDC or customer-SSO-only were chosen instead. The same
check applies to any residency requirement, not just that one.

## Evidence signing

Evidence-signing key management is a related but separate decision --
see `docs/runbooks/key-rotation.md` and `cairn_adapters.evidence_kms`
for using a real KMS-backed key instead of the process-local default
signer, which is for tests and local exploration only and does not
survive a restart.
