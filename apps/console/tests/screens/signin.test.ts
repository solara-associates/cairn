import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "../../src/router";
import { renderSignIn } from "../../src/screens/signin";
import { getSession, resetSession } from "../../src/state";

function setup(): { container: HTMLElement; router: Router } {
  document.body.innerHTML = '<div id="app"></div>';
  const container = document.querySelector<HTMLElement>("#app")!;
  const router = new Router(container, "sign-in");
  router.register({ name: "sign-in", render: (c) => renderSignIn(c, router) });
  router.register({ name: "projects", render: (c) => { c.textContent = "projects screen"; } });
  return { container, router };
}

describe("renderSignIn", () => {
  beforeEach(() => resetSession());

  it("stores the token and navigates to projects on submit", async () => {
    const { container, router } = setup();
    renderSignIn(container, router);

    const textarea = container.querySelector<HTMLTextAreaElement>("#token")!;
    textarea.value = "a-real-looking-token";
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    expect(getSession().token).toBe("a-real-looking-token");
    await vi.waitFor(() => expect(container.textContent).toBe("projects screen"));
  });

  it("shows an error and does not navigate when the token is blank", () => {
    const { container } = setup();
    renderSignIn(container, new Router(container, "sign-in"));

    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    const error = container.querySelector<HTMLElement>("[data-slot='error']")!;
    expect(error.hidden).toBe(false);
    expect(error.textContent).toContain("required");
    expect(getSession().token).toBeNull();
  });
});
