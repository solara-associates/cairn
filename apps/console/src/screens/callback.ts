import { setHtml } from "../dom";
import { loadConfig } from "../config";
import { handleCallback } from "../oidc";
import { Router } from "../router";

/** The identity provider's redirect lands here (`redirectUri` in the
 * console's OIDC config). Exchanges the authorization code for tokens,
 * then moves on to the real journey -- or back to sign-in with an error
 * on failure. The query string is stripped via `history.replaceState` so
 * a reload doesn't try to redeem the same code twice. */
export async function renderCallback(container: HTMLElement, router: Router): Promise<void> {
  setHtml(container, `<p role="status">Completing sign-in...</p>`);

  const search = window.location.search;
  window.history.replaceState(null, "", window.location.pathname + window.location.hash);

  try {
    const config = await loadConfig();
    await handleCallback(config.oidc, search);
    await router.go("projects");
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown error";
    sessionStorage.setItem("cairn.oidc.lastError", detail);
    await router.go("sign-in");
  }
}
