import { describe, expect, it } from "vitest";
import { Router } from "../src/router";

describe("Router", () => {
  it("renders the default route when the hash is empty", async () => {
    document.body.innerHTML = '<div id="app"></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "home");
    router.register({
      name: "home",
      render: (c) => {
        c.textContent = "home screen";
      },
    });

    await router.go("does-not-exist");

    expect(container.textContent).toBe("home screen");
  });

  it("go() clears the container before rendering the next route", async () => {
    document.body.innerHTML = '<div id="app"><p>stale content</p></div>';
    const container = document.querySelector<HTMLElement>("#app")!;
    const router = new Router(container, "home");
    router.register({ name: "home", render: () => {} });
    router.register({
      name: "next",
      render: (c) => {
        c.textContent = "next screen";
      },
    });

    await router.go("next");

    expect(container.innerHTML).toBe("next screen");
  });
});
