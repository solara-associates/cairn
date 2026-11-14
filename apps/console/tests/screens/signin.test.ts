import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderSignIn } from "../../src/screens/signin";
import { resetSession } from "../../src/state";
import * as config from "../../src/config";
import * as oidc from "../../src/oidc";

function setup(): HTMLElement {
  document.body.innerHTML = '<div id="app"></div>';
  sessionStorage.clear();
  return document.querySelector<HTMLElement>("#app")!;
}

describe("renderSignIn", () => {
  beforeEach(() => {
    resetSession();
    vi.restoreAllMocks();
  });

  it("starts the OIDC redirect with the loaded configuration on click", async () => {
    const container = setup();
    const oidcConfig = {
      issuer: "https://issuer.example.test",
      clientId: "cairn-console",
      redirectUri: "http://localhost/callback",
      scope: "openid email profile",
    };
    vi.spyOn(config, "loadConfig").mockResolvedValue({ oidc: oidcConfig });
    const startLoginSpy = vi.spyOn(oidc, "startLogin").mockResolvedValue(undefined);

    renderSignIn(container);
    container.querySelector<HTMLButtonElement>("[data-action='start-sign-in']")!.click();

    await vi.waitFor(() => expect(startLoginSpy).toHaveBeenCalledWith(oidcConfig));
  });

  it("shows an error when starting sign-in fails", async () => {
    const container = setup();
    vi.spyOn(config, "loadConfig").mockRejectedValue(new Error("no config.json"));

    renderSignIn(container);
    container.querySelector<HTMLButtonElement>("[data-action='start-sign-in']")!.click();

    const error = await vi.waitFor(() => {
      const slot = container.querySelector<HTMLElement>("[data-slot='error']")!;
      expect(slot.hidden).toBe(false);
      return slot;
    });
    expect(error.textContent).toContain("no config.json");
  });

  it("surfaces a stored callback error from a prior failed sign-in", () => {
    const container = setup();
    sessionStorage.setItem("cairn.oidc.lastError", "sign-in response did not match");

    renderSignIn(container);

    const error = container.querySelector<HTMLElement>("[data-slot='error']")!;
    expect(error.hidden).toBe(false);
    expect(error.textContent).toContain("sign-in response did not match");
    expect(sessionStorage.getItem("cairn.oidc.lastError")).toBeNull();
  });
});
