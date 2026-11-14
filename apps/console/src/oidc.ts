/** Provider-agnostic OIDC authorization-code flow with PKCE (RFC 7636),
 * driven entirely by the browser as a public client -- no client secret,
 * no provider-specific code. Every provider detail (issuer, client ID,
 * redirect URI, scope) comes from `config.ts`'s runtime configuration;
 * this module only ever talks to the generic endpoints a spec-compliant
 * OIDC provider publishes via its discovery document
 * (`${issuer}/.well-known/openid-configuration`).
 *
 * Tokens minted by this flow are verified server-side by the existing,
 * already-tested `cairn_adapters.auth_oidc.JwtAuthenticator` /
 * `cairn_api.AuthMiddleware` -- this module's job ends at handing the API
 * a bearer token. */
import { type OidcConfig } from "./config";
import { resetSession, setToken } from "./state";

type DiscoveryDocument = {
  authorization_endpoint: string;
  token_endpoint: string;
};

type TokenResponse = {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  token_type: string;
};

const PKCE_VERIFIER_KEY = "cairn.oidc.verifier";
const PKCE_STATE_KEY = "cairn.oidc.state";

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

async function sha256Base64Url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return base64Url(new Uint8Array(digest));
}

async function discover(issuer: string): Promise<DiscoveryDocument> {
  const response = await fetch(`${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error(`OIDC discovery failed for issuer ${issuer} (${response.status})`);
  }
  return (await response.json()) as DiscoveryDocument;
}

/** Starts the login redirect: generates and stores a PKCE verifier/state
 * pair, then navigates the browser to the provider's authorization
 * endpoint. Call from the sign-in screen's button handler. */
export async function startLogin(config: OidcConfig): Promise<void> {
  const discovery = await discover(config.issuer);
  const verifier = randomString(32);
  const challenge = await sha256Base64Url(verifier);
  const state = randomString(16);

  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(PKCE_STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  window.location.assign(`${discovery.authorization_endpoint}?${params.toString()}`);
}

/** True when the current URL carries an authorization-code callback
 * (`?code=...&state=...` or `?error=...`), so the app can decide whether
 * to run `handleCallback` before rendering the normal router. */
export function isOidcCallback(search: string): boolean {
  const params = new URLSearchParams(search);
  return params.has("code") || params.has("error");
}

export class OidcCallbackError extends Error {}

/** Completes the flow after the provider redirects back: validates
 * `state`, exchanges the authorization code (+ the stored PKCE verifier)
 * for tokens at the provider's token endpoint, and stores the resulting
 * session. Throws `OidcCallbackError` on any mismatch or provider error --
 * the caller should route back to sign-in and show the message. */
export async function handleCallback(config: OidcConfig, search: string): Promise<void> {
  const params = new URLSearchParams(search);
  const error = params.get("error");
  if (error) {
    throw new OidcCallbackError(params.get("error_description") ?? error);
  }

  const code = params.get("code");
  const returnedState = params.get("state");
  const expectedState = sessionStorage.getItem(PKCE_STATE_KEY);
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);

  if (!code || !expectedState || !returnedState || returnedState !== expectedState || !verifier) {
    throw new OidcCallbackError("sign-in response did not match the request that started it");
  }

  const discovery = await discover(config.issuer);
  const tokens = await exchangeToken(discovery.token_endpoint, {
    grant_type: "authorization_code",
    code,
    redirect_uri: config.redirectUri,
    client_id: config.clientId,
    code_verifier: verifier,
  });
  applyTokens(tokens);
}

/** Silently renews the access token using the stored refresh token.
 * Returns `false` (and leaves the session untouched) when there is no
 * refresh token to use. */
export async function refreshAccessToken(config: OidcConfig, refreshToken: string): Promise<void> {
  const discovery = await discover(config.issuer);
  const tokens = await exchangeToken(discovery.token_endpoint, {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: config.clientId,
  });
  applyTokens(tokens);
}

async function exchangeToken(
  tokenEndpoint: string,
  body: Record<string, string>,
): Promise<TokenResponse> {
  const response = await fetch(tokenEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body).toString(),
  });
  if (!response.ok) {
    throw new OidcCallbackError(`token exchange failed (${response.status})`);
  }
  return (await response.json()) as TokenResponse;
}

function applyTokens(tokens: TokenResponse): void {
  resetSession();
  const expiresAt = tokens.expires_in ? Date.now() + tokens.expires_in * 1000 : null;
  setToken(tokens.access_token, tokens.refresh_token ?? null, expiresAt);
}
