import { setHtml, showError } from "../dom";
import { loadConfig } from "../config";
import { startLogin } from "../oidc";

/** Real provider-agnostic OIDC sign-in: redirects the browser to the
 * configured identity provider's authorization endpoint (authorization
 * code + PKCE). The provider handles the actual login UI; this screen's
 * only job is starting that redirect and surfacing a clear error if the
 * console isn't configured yet. See `callback.ts` for the return leg. */
export function renderSignIn(container: HTMLElement): void {
  setHtml(
    container,
    `
    <section>
      <h1>Sign in</h1>
      <p>Sign in with your organisation's identity provider to continue.</p>
      <button type="button" data-action="start-sign-in">Sign in</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  container
    .querySelector<HTMLButtonElement>("[data-action='start-sign-in']")!
    .addEventListener("click", () => {
      void beginLogin(container);
    });

  const lastError = sessionStorage.getItem("cairn.oidc.lastError");
  if (lastError) {
    sessionStorage.removeItem("cairn.oidc.lastError");
    showError(container, lastError);
  }
}

async function beginLogin(container: HTMLElement): Promise<void> {
  try {
    const config = await loadConfig();
    await startLogin(config.oidc);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown error";
    showError(container, `Could not start sign-in: ${detail}`);
  }
}
