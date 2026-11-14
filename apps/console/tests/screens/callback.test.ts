import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderCallback } from "../../src/screens/callback";
import { Router } from "../../src/router";
import { resetSession } from "../../src/state";
import * as config from "../../src/config";
import * as oidc from "../../src/oidc";

function setup(search: string): { container: HTMLElement; router: Router } {
  document.body.innerHTML = '<div id="app"></div>';
  window.history.replaceState(null, "", `/${search}`);
  sessionStorage.clear();
  const container = document.querySelector<HTMLElement>("#app")!;
  const router = new Router(container, "sign-in");
  router.register({ name: "sign-in", render: (c) => { c.textContent = "sign-in screen"; } });
  router.register({ name: "projects", render: (c) => { c.textContent = "projects screen"; } });
  return { container, router };
}

describe("renderCallback", () => {
  beforeEach(() => {
    resetSession();
    vi.restoreAllMocks();
  });

  it("completes the token exchange and moves on to the journey", async () => {
    const { container, router } = setup("?code=abc&state=xyz");
    const oidcConfig = {
      issuer: "https://issuer.example.test",
      clientId: "cairn-console",
      redirectUri: "http://localhost/callback",
      scope: "openid email profile",
    };
    vi.spyOn(config, "loadConfig").mockResolvedValue({ oidc: oidcConfig });
    vi.spyOn(oidc, "handleCallback").mockResolvedValue(undefined);

    await renderCallback(container, router);

    expect(container.textContent).toBe("projects screen");
    expect(window.location.search).toBe("");
  });

  it("routes back to sign-in with an error when the exchange fails", async () => {
    const { container, router } = setup("?error=access_denied");
    vi.spyOn(config, "loadConfig").mockResolvedValue({
      oidc: {
        issuer: "https://issuer.example.test",
        clientId: "cairn-console",
        redirectUri: "http://localhost/callback",
        scope: "openid",
      },
    });
    vi.spyOn(oidc, "handleCallback").mockRejectedValue(new Error("access_denied"));

    await renderCallback(container, router);

    expect(container.textContent).toBe("sign-in screen");
    expect(sessionStorage.getItem("cairn.oidc.lastError")).toBe("access_denied");
  });
});
