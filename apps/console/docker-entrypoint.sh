#!/bin/sh
# Runs as one of nginx's own /docker-entrypoint.d/ scripts (sourced by
# the base image's entrypoint before it execs nginx itself -- this must
# not exec anything). Generates the runtime config.json the SPA fetches
# at startup (src/config.ts) from environment variables, so one built
# image works against whichever OIDC provider a deployment points it at
# -- no provider-specific code or rebuild per deployment (ADR-013).
set -eu

: "${CAIRN_CONSOLE_OIDC_ISSUER:?CAIRN_CONSOLE_OIDC_ISSUER is required}"
: "${CAIRN_CONSOLE_OIDC_CLIENT_ID:?CAIRN_CONSOLE_OIDC_CLIENT_ID is required}"
: "${CAIRN_CONSOLE_OIDC_REDIRECT_URI:?CAIRN_CONSOLE_OIDC_REDIRECT_URI is required}"
: "${CAIRN_CONSOLE_OIDC_SCOPE:=openid email profile offline_access}"

cat > /usr/share/nginx/html/config.json <<EOF
{
  "oidc": {
    "issuer": "${CAIRN_CONSOLE_OIDC_ISSUER}",
    "clientId": "${CAIRN_CONSOLE_OIDC_CLIENT_ID}",
    "redirectUri": "${CAIRN_CONSOLE_OIDC_REDIRECT_URI}",
    "scope": "${CAIRN_CONSOLE_OIDC_SCOPE}"
  }
}
EOF
