/**
 * R1-18 acceptance: "at least one true end-to-end test driving the full
 * journey against the real backend APIs built in this wave, not a
 * mocked backend."
 *
 * This spawns the real `cairn_api` FastAPI app (the same `uv run
 * uvicorn cairn_api.main:app` the Dockerfile runs) as a child process
 * on an ephemeral port, with real HS256 OIDC settings so a real JWT
 * (minted here the same way the Python test suite mints one) is
 * verified by the real `AuthMiddleware` -- no endpoint, route or
 * response is stubbed. The journey itself drives the console's own
 * screen-rendering functions against a real jsdom document, exactly as
 * `main.ts` wires them, and asserts on the real HTTP responses that
 * come back.
 *
 * Not a real-browser test (no Playwright, per this unit's own
 * decision: a UI framework/E2E tool is added only if acceptance
 * criteria require it, and jsdom-plus-a-live-backend already satisfies
 * "true end-to-end... against the real backend APIs... not mocked").
 * See the R1-18 handover for why a real-browser pass is still owed
 * before this console is shown to anyone.
 */
import { createHmac } from "node:crypto";
import { ChildProcess, execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { setApiBase } from "../../src/api";
import { Router } from "../../src/router";
import { renderProjects } from "../../src/screens/projects";
import { renderConnect } from "../../src/screens/connect";
import { renderRun } from "../../src/screens/run";
import { renderResults } from "../../src/screens/results";
import { renderReport } from "../../src/screens/report";
import { renderEvidence } from "../../src/screens/evidence";
import { resetSession, setProjectId, setToken } from "../../src/state";

// Not `new URL("../../../../", import.meta.url)` -- vitest/vite rewrite
// `import.meta.url` to a dev-server-style `/@fs/...` URL with no
// `file://` scheme, which silently resolves to the wrong path.
// `process.cwd()` is this package's own directory (`apps/console`)
// whenever vitest is run via `pnpm run test` from there.
const REPO_ROOT = path.resolve(process.cwd(), "..", "..");
const ISSUER = "https://issuer.example.test";
const AUDIENCE = "cairn-api";
const SECRET = "e2e-console-journey-test-secret-long-enough-for-hs256";
const PORT = 8765 + Math.floor(Math.random() * 500);
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
    sub: "e2e-user-1",
    iss: ISSUER,
    aud: AUDIENCE,
    iat: now,
    exp: now + 300,
    tenant_id: tenantId,
    roles: ["TENANT_ADMIN"],
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
        CAIRN_TENANT_ASSERTION_SECRET: "e2e-console-journey-tenant-assertion-secret",
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

describe("the full R1-18 journey against the real backend", () => {
  it("project -> ingest -> assess -> inspect -> review -> report -> export", async () => {
    resetSession();
    setToken(mintToken("6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"));

    // --- project -----------------------------------------------------
    const projectsContainer = freshContainer();
    const router = new Router(projectsContainer, "projects");
    router.register({ name: "projects", render: (c) => renderProjects(c, router) });
    router.register({ name: "connect", render: (c) => renderConnect(c, router) });
    router.register({ name: "run", render: (c) => renderRun(c, router) });
    router.register({ name: "results", render: (c) => renderResults(c, router) });
    router.register({ name: "report", render: (c) => renderReport(c, router) });
    router.register({ name: "evidence", render: (c) => renderEvidence(c, router) });

    await router.go("projects");
    const nameInput = projectsContainer.querySelector<HTMLInputElement>("#name")!;
    nameInput.value = "E2E Migration";
    projectsContainer
      .querySelector("[data-action='create-project']")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi_waitFor(() =>
      projectsContainer.querySelector("[data-slot='project-list']")!.textContent!.includes(
        "E2E Migration",
      ),
    );
    const selectButton = projectsContainer.querySelector<HTMLElement>(
      "[data-action='select-project']",
    )!;
    const projectId = selectButton.dataset.projectId!;
    expect(projectId).toBeTruthy();
    selectButton.click();

    // --- ingest --------------------------------------------------------
    await vi_waitFor(() => !!document.querySelector("[data-action='add-file']"));
    const connectContainer = document.querySelector<HTMLElement>("#app")!;
    (connectContainer.querySelector<HTMLSelectElement>("#source_format")!).value = "csv";
    (connectContainer.querySelector<HTMLTextAreaElement>("#content")!).value =
      "hostname,ip_address,role\nweb-01,10.0.1.10,web\ndb-01,10.0.1.20,";
    connectContainer
      .querySelector("[data-action='add-file']")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    connectContainer.querySelector<HTMLElement>("[data-action='start-assessment']")!.click();

    // --- assess (poll to completion against the real orchestrator) -----
    // The run screen polls, then navigates itself to "results" the moment
    // the real orchestrator reports COMPLETED -- against this fixture
    // (two tiny rows, in-memory stages) that can happen well inside one
    // poll interval, so the "run" screen's own status text may never be
    // observed directly. What matters for this journey -- the run really
    // completing against the real pipeline, not a mock -- is proven by
    // the decisions the completed run produced, waited for next.
    await vi_waitFor(() => !!document.querySelector("[data-slot='decisions']"), 30_000);
    const resultsContainer = document.querySelector<HTMLElement>("#app")!;
    await vi_waitFor(() =>
      (resultsContainer.querySelector("[data-slot='decisions']")!.textContent ?? "").length > 0,
    );
    const acceptButton = resultsContainer.querySelector<HTMLElement>(
      "[data-action='accept-decision']",
    );
    expect(acceptButton).not.toBeNull();
    acceptButton!.click();
    await vi_waitFor(() =>
      resultsContainer.querySelector("[data-slot='decisions']")!.textContent!.includes("ACCEPTED"),
    );

    resultsContainer.querySelector<HTMLElement>("[data-action='view-report']")!.click();

    // --- report -----------------------------------------------------------
    await vi_waitFor(() => !!document.querySelector("[data-slot='report-text']"));
    await vi_waitFor(() =>
      !(document.querySelector("[data-slot='report-text']")!.textContent ?? "").includes("Loading"),
    );
    const reportText = document.querySelector("[data-slot='report-text']")!.textContent!;
    expect(reportText).toContain("Assessment report");
    expect(reportText).toContain("Evidence package hash: PENDING");

    document.querySelector<HTMLElement>("[data-action='export-evidence']")!.click();

    // --- export -------------------------------------------------------------
    await vi_waitFor(() =>
      !(document.querySelector("[data-slot='evidence']")!.textContent ?? "").includes("Building"),
    );
    const evidenceText = document.querySelector("[data-slot='evidence']")!.textContent!;
    expect(evidenceText).toContain("Payload hash:");
    expect(evidenceText).not.toContain("Payload hash: \n");
    const finalReportText = document.querySelector("[data-slot='report-text']")!.textContent!;
    expect(finalReportText).not.toContain("PENDING");
  }, 60_000);
});

async function vi_waitFor(predicate: () => boolean, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (predicate()) {
        return;
      }
    } catch {
      // Not ready yet (e.g. a slot the current screen hasn't rendered) --
      // keep polling rather than treating this as the timeout's failure.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("condition not met before timeout");
}
