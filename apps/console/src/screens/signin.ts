import { onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { setToken } from "../state";

/** A real OIDC login flow does not exist in this codebase yet -- R0-09's
 * auth middleware verifies a bearer token issued by an external identity
 * provider, but no provider is wired into a deployment yet. This screen
 * is an honest stand-in: the operator pastes an already-issued access
 * token (the one a pilot's identity provider would hand them) rather
 * than the console inventing a fake login UI around credentials it
 * cannot actually check. Flagged in the handover as not demo-ready on
 * its own. */
export function renderSignIn(container: HTMLElement, router: Router): void {
  setHtml(
    container,
    `
    <section>
      <h1>Sign in</h1>
      <p>Paste an access token issued for CAIRN (see your pilot's identity provider).</p>
      <form data-action="sign-in">
        <label for="token">Access token</label>
        <textarea id="token" name="token" rows="3" required></textarea>
        <button type="submit">Continue</button>
      </form>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  onSubmit(container, "sign-in", (_event, form) => {
    const token = formValue(form, "token").trim();
    if (!token) {
      showError(container, "An access token is required.");
      return;
    }
    setToken(token);
    void router.go("projects");
  });
}
