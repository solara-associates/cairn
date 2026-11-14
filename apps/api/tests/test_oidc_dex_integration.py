"""console OIDC sign-in acceptance: the OIDC authorization-code+PKCE flow, RBAC role
mapping, tenant isolation, token refresh and wrong-issuer rejection all
proven against a REAL local OIDC provider (`dexidp/dex`), not a hand-minted
JWT. ``test_auth_oidc.py`` and ``test_projects_api.py`` already cover the
claim-parsing and RBAC logic unit-by-unit against crafted tokens; this file
proves the same code path end to end against a real spec-compliant
provider's real discovery document, real authorization endpoint, real
PKCE-protected token endpoint and real RS256-signed, JWKS-verified tokens.

Dex's ``authproxy`` connector (a real, shipped connector -- not something
built for this test) trusts the caller to assert an already-authenticated
identity via headers, exactly like it would trust an upstream
authenticating reverse proxy in production. That lets this test act as
"the identity provider's own login step" for a deterministic test user
without needing a browser: everything downstream of that -- discovery, the
`code_challenge`/`code_verifier` exchange, JWKS fetch, signature
verification, claim mapping into a ``Principal``, RBAC and tenant scoping --
is the real, unmodified, provider-agnostic path CAIRN ships.

No CAIRN code here is dex-specific: ``OidcSettings``/``JwtAuthenticator``
only ever read ``tenant_claim``/``roles_claim`` by name, configured here to
dex's own `name` and `groups` claims -- the same configuration knobs a real
deployment would point at whatever claims its real IdP populates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
from collections.abc import Iterator

import httpx
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_api import create_app
from fastapi.testclient import TestClient

DEX_IMAGE = "dexidp/dex:v2.41.1"
CLIENT_ID = "cairn-console"
REDIRECT_URI = "http://127.0.0.1:9999/callback"
TENANT_A = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
TENANT_B = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="real OIDC provider test needs a local docker daemon",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _dex_config(issuer: str, *, id_tokens_expiry: str = "24h") -> str:
    return f"""
issuer: {issuer}
storage:
  type: memory
web:
  http: 0.0.0.0:5556
oauth2:
  skipApprovalScreen: true
expiry:
  idTokens: {id_tokens_expiry}
  signingKeys: 6h
  authRequests: 24h
staticClients:
- id: {CLIENT_ID}
  public: true
  redirectURIs:
  - '{REDIRECT_URI}'
  name: 'CAIRN Console'
enablePasswordDB: true
staticPasswords:
- email: "refresh-test@tenant-a.test"
  # bcrypt hash of "password" -- this is a disposable test-only identity
  # in a throwaway in-memory dex instance, not a real credential.
  hash: "$2a$10$2b2cU8CPhOTaGrs1HRQuAueS7JTT5ZHsHSzYiFPm1leZck7Mc8T4W"
  username: "{TENANT_A}"
  userID: "refresh-test-user"
connectors:
- type: authproxy
  id: proxy
  name: Proxy
  config:
    userHeader: X-Remote-User
    emailHeader: X-Remote-Email
    groupHeader: X-Remote-Group
"""


class DexServer:
    def __init__(self, port: int, container_id: str) -> None:
        self.port = port
        self.container_id = container_id
        self.issuer = f"http://127.0.0.1:{port}/dex"

    def jwks_url(self) -> str:
        return f"{self.issuer}/keys"


def _start_dex(tmp_path_factory: pytest.TempPathFactory, *, id_tokens_expiry: str = "24h") -> DexServer:
    port = _free_port()
    config_dir = tmp_path_factory.mktemp("dex-config")
    config_path = config_dir / "config.yaml"
    issuer = f"http://127.0.0.1:{port}/dex"
    config_path.write_text(_dex_config(issuer, id_tokens_expiry=id_tokens_expiry))

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p",
            f"127.0.0.1:{port}:5556",
            "-v",
            f"{config_path}:/cfg.yaml:ro",
            DEX_IMAGE,
            "dex",
            "serve",
            "/cfg.yaml",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    container_id = result.stdout.strip()
    server = DexServer(port, container_id)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{server.issuer}/.well-known/openid-configuration", timeout=1)
            if response.status_code == 200:
                return server
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    subprocess.run(["docker", "rm", "-f", container_id], check=False, capture_output=True)
    raise RuntimeError("dex did not become ready in time")


def _stop_dex(server: DexServer) -> None:
    subprocess.run(["docker", "rm", "-f", server.container_id], check=False, capture_output=True)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _login_via_authproxy(
    server: DexServer,
    *,
    remote_user: str,
    remote_email: str,
    remote_groups: list[str],
    scope: str = "openid email profile groups",
) -> dict[str, str]:
    """Drives the real authorization-code + PKCE flow a public client (the
    console) would drive, using dex's authproxy connector to assert an
    already-authenticated identity the way an upstream auth proxy would in
    production. Returns the real token response from dex's own /token
    endpoint."""
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(os.urandom(16))
    headers = {
        "X-Remote-User": remote_user,
        "X-Remote-Email": remote_email,
        "X-Remote-Group": ",".join(remote_groups),
    }

    with httpx.Client(follow_redirects=False, timeout=5) as client:
        authorize_params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        response = client.get(
            f"{server.issuer}/auth/proxy",
            params=authorize_params,
            headers=headers,
        )
        assert response.status_code == 302, response.text
        callback_location = response.headers["location"]

        response = client.get(callback_location, headers=headers)
        assert response.status_code == 303, response.text
        final_redirect = response.headers["location"]

        code = urllib.parse.parse_qs(urllib.parse.urlparse(final_redirect).query)["code"][0]

        response = client.post(
            f"{server.issuer}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


def _login_via_local_connector(server: DexServer, *, scope: str) -> dict[str, str]:
    """dex's `authproxy` connector (used above) is stateless by design --
    it has nothing to refresh against, so it never issues a refresh
    token. The refresh-token flow is only meaningful for a connector
    that owns a real session, so this drives the same real PKCE flow
    through dex's local username/password connector instead, which
    does support `offline_access`."""
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(os.urandom(16))

    with httpx.Client(follow_redirects=False, timeout=5) as client:
        response = client.get(
            f"{server.issuer}/auth/local",
            params={
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302, response.text
        login_url = urllib.parse.urljoin(server.issuer, response.headers["location"])

        response = client.post(
            login_url,
            data={"login": "refresh-test@tenant-a.test", "password": "password"},
        )
        assert response.status_code == 303, response.text
        final_redirect = response.headers["location"]
        code = urllib.parse.parse_qs(urllib.parse.urlparse(final_redirect).query)["code"][0]

        response = client.post(
            f"{server.issuer}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


def _refresh(server: DexServer, refresh_token: str) -> dict[str, str]:
    with httpx.Client(timeout=5) as client:
        response = client.post(
            f"{server.issuer}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


def _claims(jwt_token: str) -> dict[str, object]:
    payload_segment = jwt_token.split(".")[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _authenticator_for(server: DexServer) -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(
            issuer=server.issuer,
            audience=CLIENT_ID,
            algorithms=("RS256",),
            jwks_url=server.jwks_url(),
            tenant_claim="name",
            roles_claim="groups",
        )
    )


def _client_for(server: DexServer) -> TestClient:
    app = create_app(
        authenticator=_authenticator_for(server),
        assertion_secret=b"test-oidc-dex-integration-assertion-secret",
    )
    return TestClient(app)


@pytest.fixture(scope="module")
def dex(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DexServer]:
    server = _start_dex(tmp_path_factory)
    try:
        yield server
    finally:
        _stop_dex(server)


def test_discovery_document_is_a_real_oidc_metadata_document(dex: DexServer) -> None:
    response = httpx.get(f"{dex.issuer}/.well-known/openid-configuration", timeout=5)
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["issuer"] == dex.issuer
    assert "authorization_endpoint" in metadata
    assert "token_endpoint" in metadata
    assert metadata["jwks_uri"] == dex.jwks_url()


def test_real_login_maps_tenant_and_grants_access_for_a_sufficient_role(dex: DexServer) -> None:
    tokens = _login_via_authproxy(
        dex,
        remote_user=TENANT_A,
        remote_email="allan@tenant-a.test",
        remote_groups=["TENANT_ADMIN"],
    )
    client = _client_for(dex)
    response = client.post(
        "/v1/projects",
        json={"name": "Dex-verified project"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["tenant_id"] == TENANT_A


def test_real_login_with_insufficient_role_is_forbidden(dex: DexServer) -> None:
    tokens = _login_via_authproxy(
        dex,
        remote_user=TENANT_A,
        remote_email="viewer@tenant-a.test",
        remote_groups=["VIEWER"],
    )
    client = _client_for(dex)
    response = client.post(
        "/v1/projects",
        json={"name": "Should be forbidden"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 403


def test_tenant_isolation_across_two_real_logins(dex: DexServer) -> None:
    client = _client_for(dex)

    tokens_a = _login_via_authproxy(
        dex, remote_user=TENANT_A, remote_email="a@tenant-a.test", remote_groups=["TENANT_ADMIN"]
    )
    create_response = client.post(
        "/v1/projects",
        json={"name": "Tenant A's project"},
        headers={"Authorization": f"Bearer {tokens_a['access_token']}"},
    )
    assert create_response.status_code == 201

    tokens_b = _login_via_authproxy(
        dex, remote_user=TENANT_B, remote_email="b@tenant-b.test", remote_groups=["TENANT_ADMIN"]
    )
    list_response = client.get(
        "/v1/projects",
        headers={"Authorization": f"Bearer {tokens_b['access_token']}"},
    )
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_refresh_token_issues_a_new_valid_access_token(dex: DexServer) -> None:
    tokens = _login_via_local_connector(dex, scope="openid email profile offline_access")
    assert "refresh_token" in tokens

    refreshed = _refresh(dex, tokens["refresh_token"])
    original_exp = _claims(tokens["access_token"])["exp"]
    refreshed_exp = _claims(refreshed["access_token"])["exp"]
    assert refreshed_exp >= original_exp

    # The refreshed token must be a real, independently verifiable token --
    # same issuer, same signature chain, not just structurally present.
    authenticator = _authenticator_for(dex)
    principal = authenticator.verify(refreshed["access_token"])
    assert principal.subject


def test_expired_token_is_rejected(tmp_path_factory: pytest.TempPathFactory) -> None:
    server = _start_dex(tmp_path_factory, id_tokens_expiry="2s")
    try:
        tokens = _login_via_authproxy(
            server,
            remote_user=TENANT_A,
            remote_email="a@tenant-a.test",
            remote_groups=["TENANT_ADMIN"],
        )
        time.sleep(3)
        client = _client_for(server)
        response = client.get(
            "/v1/projects",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert response.status_code == 401
    finally:
        _stop_dex(server)


def test_token_from_a_different_issuer_is_rejected(
    dex: DexServer, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other_issuer_server = _start_dex(tmp_path_factory)
    try:
        other_tokens = _login_via_authproxy(
            other_issuer_server,
            remote_user=TENANT_A,
            remote_email="a@tenant-a.test",
            remote_groups=["TENANT_ADMIN"],
        )
        # cairn_api is configured for `dex`'s issuer/JWKS, not the other
        # dex instance's -- a token signed by a key dex never published
        # under its own JWKS must be rejected.
        client = _client_for(dex)
        response = client.get(
            "/v1/projects",
            headers={"Authorization": f"Bearer {other_tokens['access_token']}"},
        )
        assert response.status_code == 401
    finally:
        _stop_dex(other_issuer_server)
