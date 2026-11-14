import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  OidcCallbackError,
  handleCallback,
  isOidcCallback,
  refreshAccessToken,
  startLogin,
} from "../src/oidc";
import { getSession, resetSession } from "../src/state";

const CONFIG = {
  issuer: "https://issuer.example.test",
  clientId: "cairn-console",
  redirectUri: "http://localhost/callback",
  scope: "openid email profile",
};

const DISCOVERY = {
  authorization_endpoint: "https://issuer.example.test/auth",
  token_endpoint: "https://issuer.example.test/token",
};

function mockDiscoveryAnd(tokenResponse: unknown, tokenStatus = 200): void {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/.well-known/openid-configuration")) {
      return new Response(JSON.stringify(DISCOVERY), { status: 200 });
    }
    if (url === DISCOVERY.token_endpoint) {
      return new Response(JSON.stringify(tokenResponse), { status: tokenStatus });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
}

describe("isOidcCallback", () => {
  it("is true with a code param", () => {
    expect(isOidcCallback("?code=abc&state=xyz")).toBe(true);
  });
  it("is true with an error param", () => {
    expect(isOidcCallback("?error=access_denied")).toBe(true);
  });
  it("is false otherwise", () => {
    expect(isOidcCallback("")).toBe(false);
    expect(isOidcCallback("?foo=bar")).toBe(false);
  });
});

function stubLocationAssign(): ReturnType<typeof vi.fn> {
  const assignSpy = vi.fn();
  // jsdom's `window.location.assign` isn't a configurable property, so
  // `vi.spyOn` can't touch it directly -- replace the whole `location`
  // object instead.
  Object.defineProperty(window, "location", {
    value: { ...window.location, assign: assignSpy },
    writable: true,
  });
  return assignSpy;
}

describe("startLogin", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    resetSession();
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  it("discovers the provider, stores a PKCE verifier/state pair, and redirects with a matching challenge", async () => {
    mockDiscoveryAnd({});
    const assignSpy = stubLocationAssign();

    await startLogin(CONFIG);

    expect(assignSpy).toHaveBeenCalledTimes(1);
    const redirectUrl = new URL(assignSpy.mock.calls[0][0] as string);
    expect(redirectUrl.origin + redirectUrl.pathname).toBe(DISCOVERY.authorization_endpoint);
    expect(redirectUrl.searchParams.get("response_type")).toBe("code");
    expect(redirectUrl.searchParams.get("client_id")).toBe(CONFIG.clientId);
    expect(redirectUrl.searchParams.get("redirect_uri")).toBe(CONFIG.redirectUri);
    expect(redirectUrl.searchParams.get("code_challenge_method")).toBe("S256");

    const storedState = sessionStorage.getItem("cairn.oidc.state");
    const storedVerifier = sessionStorage.getItem("cairn.oidc.verifier");
    expect(storedState).toBe(redirectUrl.searchParams.get("state"));
    expect(storedVerifier).toBeTruthy();

    // The challenge must be the real SHA-256/base64url digest of the
    // stored verifier -- not just "some value".
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(storedVerifier!),
    );
    const expectedChallenge = btoa(
      String.fromCharCode(...new Uint8Array(digest)),
    )
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    expect(redirectUrl.searchParams.get("code_challenge")).toBe(expectedChallenge);
  });

  it("generates a different verifier/state on every call", async () => {
    mockDiscoveryAnd({});
    stubLocationAssign();

    await startLogin(CONFIG);
    const firstVerifier = sessionStorage.getItem("cairn.oidc.verifier");

    sessionStorage.clear();
    await startLogin(CONFIG);
    const secondVerifier = sessionStorage.getItem("cairn.oidc.verifier");

    expect(firstVerifier).not.toBe(secondVerifier);
  });
});

describe("handleCallback", () => {
  beforeEach(() => {
    resetSession();
    sessionStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("exchanges the code for tokens and stores the session when state matches", async () => {
    sessionStorage.setItem("cairn.oidc.state", "expected-state");
    sessionStorage.setItem("cairn.oidc.verifier", "the-verifier");
    mockDiscoveryAnd({
      access_token: "real-access-token",
      refresh_token: "real-refresh-token",
      expires_in: 300,
      token_type: "bearer",
    });

    await handleCallback(CONFIG, "?code=auth-code&state=expected-state");

    const session = getSession();
    expect(session.token).toBe("real-access-token");
    expect(session.refreshToken).toBe("real-refresh-token");
    expect(session.expiresAt).not.toBeNull();
    expect(sessionStorage.getItem("cairn.oidc.state")).toBeNull();
    expect(sessionStorage.getItem("cairn.oidc.verifier")).toBeNull();
  });

  it("rejects a mismatched state without calling the token endpoint", async () => {
    sessionStorage.setItem("cairn.oidc.state", "expected-state");
    sessionStorage.setItem("cairn.oidc.verifier", "the-verifier");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      handleCallback(CONFIG, "?code=auth-code&state=wrong-state"),
    ).rejects.toThrow(OidcCallbackError);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getSession().token).toBeNull();
  });

  it("surfaces a provider error param without exchanging a code", async () => {
    sessionStorage.setItem("cairn.oidc.state", "expected-state");
    sessionStorage.setItem("cairn.oidc.verifier", "the-verifier");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      handleCallback(CONFIG, "?error=access_denied&error_description=user+said+no"),
    ).rejects.toThrow("user said no");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces a token endpoint failure", async () => {
    sessionStorage.setItem("cairn.oidc.state", "expected-state");
    sessionStorage.setItem("cairn.oidc.verifier", "the-verifier");
    mockDiscoveryAnd({ error: "invalid_grant" }, 400);

    await expect(
      handleCallback(CONFIG, "?code=auth-code&state=expected-state"),
    ).rejects.toThrow(OidcCallbackError);
  });
});

describe("refreshAccessToken", () => {
  beforeEach(() => resetSession());
  afterEach(() => vi.unstubAllGlobals());

  it("replaces the session with the refreshed tokens", async () => {
    mockDiscoveryAnd({
      access_token: "new-access-token",
      refresh_token: "rotated-refresh-token",
      expires_in: 600,
      token_type: "bearer",
    });

    await refreshAccessToken(CONFIG, "old-refresh-token");

    const session = getSession();
    expect(session.token).toBe("new-access-token");
    expect(session.refreshToken).toBe("rotated-refresh-token");
  });
});
