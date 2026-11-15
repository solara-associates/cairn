/**
 * R2-09 acceptance: "one true end-to-end test that spawns the real
 * backend and drives the full journey (pattern select -> parameterize
 * -> generate -> regenerate -> inspect caveats -> export)", the same
 * pattern R1-18's own PR #47 (``tests/e2e/journey.test.ts``) used.
 *
 * Spawns the real `cairn_api` FastAPI app as a child process on an
 * ephemeral port, with real HS256 OIDC settings so a real JWT verifies
 * against the real `AuthMiddleware` -- no route or response is stubbed.
 * The journey drives the console's own screen-rendering functions
 * against a real jsdom document, exactly as `main.ts` wires them, and
 * asserts on the real HTTP responses (the real pattern catalogue under
 * `patterns/`, the real mapping release under `mappings/service-map.
 * yaml`, a real generated target model/diagram/roadmap/IaC preview).
 */
import { createHmac } from "node:crypto";
import { ChildProcess, execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { setApiBase } from "../../src/api";
import { Router } from "../../src/router";
import { renderProjects } from "../../src/screens/projects";
import { renderPatterns } from "../../src/screens/patterns";
import { renderParameterize } from "../../src/screens/parameterize";
import { renderDesignResults } from "../../src/screens/design-results";
import { renderRoadmap } from "../../src/screens/roadmap";
import { renderIac } from "../../src/screens/iac";
import { renderDesignExport } from "../../src/screens/design-export";
import { resetSession, setToken } from "../../src/state";

// See R1-18's own e2e test for why `process.cwd()`, not
// `import.meta.url` -- vite/vitest rewrite the latter to a `/@fs/...`
// URL with no `file://` scheme.
const REPO_ROOT = path.resolve(process.cwd(), "..", "..");
const ISSUER = "https://issuer.example.test";
const AUDIENCE = "cairn-api";
const SECRET = "e2e-console-design-journey-test-secret-long-enough-for-hs256";
const PORT = 9300 + Math.floor(Math.random() * 500);
const BASE_URL = `http://127.0.0.1:${PORT}`;

function base64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

function signJwt(claims: Record<string, unknown>): string {
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = base64url(JSON.stringify(claims));
  const signature = createHmac("sha256", SECRET).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function mintToken(tenantId: string): string {
  const now = Math.floor(Date.now() / 1000);
  return signJwt({
    sub: "e2e-design-user-1",
    iss: ISSUER,
    aud: AUDIENCE,
    iat: now,
    exp: now + 300,
    tenant_id: tenantId,
    roles: ["TENANT_ADMIN", "ARCHITECT"],
  });
}

function resolveUvPath(): string {
  try {
    return execFileSync("which", ["uv"], { encoding: "utf8" }).trim();
  } catch {
    return "uv";
  }
}

let server: ChildProcess;

async function waitForHealthy(): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE_URL}/healthz`);
      if (response.ok) {
        return;
      }
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("cairn_api did not become healthy in time");
}

beforeAll(async () => {
  server = spawn(
    resolveUvPath(),
    ["run", "--no-sync", "uvicorn", "cairn_api.main:app", "--host", "127.0.0.1", "--port", String(PORT)],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        CAIRN_OIDC_ISSUER: ISSUER,
        CAIRN_OIDC_AUDIENCE: AUDIENCE,
        CAIRN_OIDC_SECRET: SECRET,
        CAIRN_TENANT_ASSERTION_SECRET: "e2e-console-design-journey-tenant-assertion-secret",
      },
      stdio: "pipe",
    },
  );
  await waitForHealthy();
  setApiBase(BASE_URL);
}, 40_000);

afterAll(() => {
  server?.kill();
});

function freshContainer(): HTMLElement {
  document.body.innerHTML = '<div id="app"></div>';
  return document.querySelector<HTMLElement>("#app")!;
}

async function waitFor(predicate: () => boolean, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (predicate()) {
        return;
      }
    } catch {
      // not ready yet -- current screen hasn't rendered this slot
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("condition not met before timeout");
}

describe("the full R2-09 design journey against the real backend", () => {
  it(
    "pattern select -> parameterize -> generate -> regenerate -> inspect caveats -> export",
    async () => {
      resetSession();
      setToken(mintToken("6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"));

      const container = freshContainer();
      const router = new Router(container, "projects");
      router.register({ name: "projects", render: (c) => renderProjects(c, router) });
      router.register({ name: "patterns", render: (c) => renderPatterns(c, router) });
      router.register({ name: "parameterize", render: (c) => renderParameterize(c, router) });
      router.register({ name: "design-results", render: (c) => renderDesignResults(c, router) });
      router.register({ name: "roadmap", render: (c) => renderRoadmap(c, router) });
      router.register({ name: "iac", render: (c) => renderIac(c, router) });
      router.register({ name: "design-export", render: (c) => renderDesignExport(c, router) });

      // --- project -------------------------------------------------------
      await router.go("projects");
      const nameInput = container.querySelector<HTMLInputElement>("#name")!;
      nameInput.value = "E2E Design Migration";
      container
        .querySelector("[data-action='create-project']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await waitFor(() =>
        (container.querySelector("[data-slot='project-list']")!.textContent ?? "").includes(
          "E2E Design Migration",
        ),
      );
      container.querySelector<HTMLElement>("[data-action='select-project-for-design']")!.click();

      // --- pattern select --------------------------------------------------
      await waitFor(() => !!document.querySelector("[data-action='select-pattern']"));
      const patternsContainer = document.querySelector<HTMLElement>("#app")!;
      expect(patternsContainer.querySelector("[data-slot='pattern-list']")!.textContent).toContain(
        "Three-tier web application",
      );
      const selectPatternButton = Array.from(
        patternsContainer.querySelectorAll<HTMLElement>("[data-action='select-pattern']"),
      ).find((button) => button.dataset.patternId === "web-app")!;
      expect(selectPatternButton).toBeTruthy();
      selectPatternButton.click();

      // --- parameterize (create) -------------------------------------------
      await waitFor(() => !!document.querySelector("#param-compute_platform"));
      const parameterizeContainer = document.querySelector<HTMLElement>("#app")!;
      (parameterizeContainer.querySelector<HTMLSelectElement>("#param-compute_platform")!).value =
        "cloud_run";
      (parameterizeContainer.querySelector<HTMLSelectElement>("#param-database_engine")!).value =
        "cloud_sql_postgres";
      (parameterizeContainer.querySelector<HTMLTextAreaElement>("#resources")!).value = [
        "res-exact,aws,secrets-manager,europe-west2",
        "res-approx,aws,s3,europe-west2",
        "res-gap,aws,secrets-manager,ap-southeast-1",
        "res-unresolved,aws,no-such-service,europe-west2",
      ].join("\n");

      parameterizeContainer
        .querySelector("[data-action='generate-design']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

      // --- design results: inspect caveats (resolved/approximate/
      // unavailable/unresolved, visibly distinguished) ----------------------
      await waitFor(() => !!document.querySelector("[data-slot='resources']"));
      const resultsContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (resultsContainer.querySelector("[data-slot='resources']")!.textContent ?? "").length > 0,
      );
      const resourcesText = resultsContainer.querySelector("[data-slot='resources']")!.textContent!;
      expect(resourcesText).toContain("Resolved");
      expect(resourcesText).toContain("Approximate match");
      expect(resourcesText).toContain("Unavailable");
      expect(resourcesText).toContain("Unresolved");

      await waitFor(() =>
        (resultsContainer.querySelector("[data-slot='revisions']")!.textContent ?? "").includes(
          "Revision 1",
        ),
      );

      // --- regenerate: new revision, old one still comparable ---------------
      resultsContainer.querySelector<HTMLElement>("[data-action='regenerate']")!.click();
      await waitFor(() => !!document.querySelector("#param-compute_platform"));
      const regenerateContainer = document.querySelector<HTMLElement>("#app")!;
      expect(regenerateContainer.querySelector("#resources")).toBeNull();
      (regenerateContainer.querySelector<HTMLSelectElement>("#param-compute_platform")!).value =
        "gke";
      regenerateContainer
        .querySelector("[data-action='generate-design']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

      await waitFor(() => !!document.querySelector("[data-slot='revisions']"));
      const resultsAfterRegenerate = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (resultsAfterRegenerate.querySelector("[data-slot='summary']")!.textContent ?? "").includes(
          "Revision: 2",
        ),
      );
      await waitFor(() =>
        (resultsAfterRegenerate.querySelector("[data-slot='revisions']")!.textContent ?? "").includes(
          "Revision 1",
        ) &&
        (resultsAfterRegenerate.querySelector("[data-slot='revisions']")!.textContent ?? "").includes(
          "Revision 2 (current)",
        ),
      );
      // the previous revision is independently viewable/comparable
      const viewRevisionOneButton = Array.from(
        resultsAfterRegenerate.querySelectorAll<HTMLElement>("[data-action='view-revision']"),
      ).find((button) => button.dataset.revisionNumber === "1")!;
      viewRevisionOneButton.click();
      await waitFor(() =>
        (resultsAfterRegenerate.querySelector("[data-slot='comparison']")!.textContent ?? "").includes(
          "cloud_run",
        ),
      );

      // --- roadmap: wave sequencing, constraints/risks shown ------------------
      resultsAfterRegenerate.querySelector<HTMLElement>("[data-action='view-roadmap']")!.click();
      await waitFor(() => !!document.querySelector("[data-slot='waves']"));
      const roadmapContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (roadmapContainer.querySelector("[data-slot='waves']")!.textContent ?? "").includes("Wave 1"),
      );

      // --- IaC preview: plan only, named gaps -------------------------------
      void router.go("iac");
      await waitFor(() => !!document.querySelector("[data-slot='disclaimer']"));
      const iacContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (iacContainer.querySelector("[data-slot='disclaimer']")!.textContent ?? "").includes(
          "PLAN ONLY",
        ),
      );
      const iacResourcesText = iacContainer.querySelector("[data-slot='resources']")!.textContent!;
      expect(iacResourcesText).toContain("Gap -- no resource planned");

      // --- export: the machine-readable bundle, version stamps consistent ---
      void router.go("design-export");
      await waitFor(() => !!document.querySelector("[data-slot='bundle']"));
      const exportContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (exportContainer.querySelector("[data-slot='bundle']")!.textContent ?? "").length > 0,
      );
      const bundleJson = JSON.parse(
        exportContainer.querySelector("[data-slot='bundle']")!.textContent!,
      );
      expect(bundleJson.version_stamps_consistent).toBe(true);
      expect(bundleJson.design.revision_number).toBe(2);
      const summaryText = exportContainer.querySelector("[data-slot='summary']")!.textContent!;
      expect(summaryText).toContain("consistent across design/diagram/plan/IaC");
      expect(summaryText).not.toContain("do not export this design");
    },
    60_000,
  );
});
