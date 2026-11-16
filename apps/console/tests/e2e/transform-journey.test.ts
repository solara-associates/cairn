/**
 * R3-07 acceptance: "one true end-to-end test that spawns the real
 * backend and drives the full journey (trigger a transformation run
 * against a connected source -> inspect the unified diff and manifest
 * -> run validation -> leave a review comment)", the same pattern
 * R2-09's own PR #66 (``tests/e2e/design-journey.test.ts``) and R1-18's
 * ``tests/e2e/journey.test.ts`` both use.
 *
 * Spawns the real `cairn_api` FastAPI app as a child process on an
 * ephemeral port, with real HS256 OIDC settings so a real JWT verifies
 * against the real `AuthMiddleware` -- no route or response is stubbed.
 * The "connected source" is a real local Git repository (`git init` +
 * one commit, in a temp directory, fetched over a `file://` URL) --
 * never a live remote -- so this run drives 721's *real*
 * `GitSourceAdapter` (a real, read-only `git clone`) feeding the *real*,
 * compiled `cairn-transform-cli`/`cairn-transform-validator-cli`
 * binaries (722-726/729's own real engine), exactly the discipline
 * `tests/golden/transform/test_golden_corpus.py` already established
 * for this exact fixture content (``terraform_acl_deprecated``) at the
 * Python layer -- this test proves the same real pipeline end to end
 * through the console's own screens instead.
 */
import { createHmac } from "node:crypto";
import { execFileSync, ChildProcess, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { setApiBase } from "../../src/api";
import { Router } from "../../src/router";
import { renderProjects } from "../../src/screens/projects";
import { renderTransformRun } from "../../src/screens/transform-run";
import { renderTransformDiff } from "../../src/screens/transform-diff";
import { renderTransformValidate } from "../../src/screens/transform-validate";
import { renderTransformEvidence } from "../../src/screens/transform-evidence";
import { renderTransformReview } from "../../src/screens/transform-review";
import { resetSession, setToken } from "../../src/state";

// See R1-18's own e2e test for why `process.cwd()`, not
// `import.meta.url` -- vite/vitest rewrite the latter to a `/@fs/...`
// URL with no `file://` scheme.
const REPO_ROOT = path.resolve(process.cwd(), "..", "..");
const ISSUER = "https://issuer.example.test";
const AUDIENCE = "cairn-api";
const SECRET = "e2e-console-transform-journey-test-secret-long-enough-for-hs256";
const PORT = 9800 + Math.floor(Math.random() * 500);
const BASE_URL = `http://127.0.0.1:${PORT}`;

// The exact fixture content `tests/golden/transform/test_golden_corpus.
// py::test_terraform_acl_deprecation_is_applied_end_to_end` already
// proves transforms deterministically through the real compiled
// pipeline: one `aws_s3_bucket` resource's deprecated inline `acl`
// attribute, APPLIED by `tf-s3-bucket-inline-acl-deprecated`, two edits
// (delete the attribute, insert the replacement resource).
const MAIN_TF_CONTENT = `resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-golden-artifacts"
  acl    = "private"
}
`;
const ACL_DEPRECATED_RULE_ID = "tf-s3-bucket-inline-acl-deprecated";

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
    sub: "e2e-transform-user-1",
    iss: ISSUER,
    aud: AUDIENCE,
    iat: now,
    exp: now + 300,
    tenant_id: tenantId,
    // TENANT_ADMIN is required to create a project at all
    // (ProjectService.CREATE_ROLES); ENGINEER satisfies every other role
    // gate this journey crosses (create/validate/evidence/review
    // transformation routes all read as ENGINEER+; read routes accept
    // any granted role) -- named explicitly rather than granting every
    // role, so this test exercises the same two-role grant a real
    // engineer setting up their own pilot project would carry.
    roles: ["TENANT_ADMIN", "ENGINEER"],
  });
}

function resolveUvPath(): string {
  try {
    return execFileSync("which", ["uv"], { encoding: "utf8" }).trim();
  } catch {
    return "uv";
  }
}

function git(args: string[], cwd: string): void {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

/** Builds a real, local Git repository (never a live remote) and
 * returns a `file://` URL to it -- the same pattern `test_source_git.
 * py::_make_local_git_repo` already establishes for this exact adapter
 * at the Python layer. */
function makeLocalGitRepo(): string {
  const repoDir = fs.mkdtempSync(path.join(os.tmpdir(), "cairn-e2e-transform-repo-"));
  git(["init", "-b", "main"], repoDir);
  git(["config", "user.email", "e2e@example.test"], repoDir);
  git(["config", "user.name", "E2E"], repoDir);
  fs.writeFileSync(path.join(repoDir, "main.tf"), MAIN_TF_CONTENT);
  git(["add", "main.tf"], repoDir);
  git(["commit", "-m", "initial"], repoDir);
  return `file://${repoDir}`;
}

let server: ChildProcess;
let repoUrl: string;

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
  repoUrl = makeLocalGitRepo();

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
        CAIRN_TENANT_ASSERTION_SECRET: "e2e-console-transform-journey-tenant-assertion-secret",
        // The real cairn-transform-cli/cairn-transform-validator-cli
        // binaries -- this unit's own worktree already built them
        // (`cargo build --release -p cairn-transform-cli -p
        // cairn-transform-validator`) for the Python test suite; the
        // CI `console` job builds them too (see `.github/workflows/
        // ci.yml`'s own change for this unit), mirroring the `python`
        // job's identical env vars exactly.
        CAIRN_TRANSFORM_CLI_BIN: path.join(REPO_ROOT, "target", "release", "cairn-transform-cli"),
        CAIRN_TRANSFORM_VALIDATOR_CLI_BIN: path.join(
          REPO_ROOT,
          "target",
          "release",
          "cairn-transform-validator-cli",
        ),
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

describe("the full R3-07 diff review and validation journey against the real backend", () => {
  it(
    "connect source -> trigger transformation -> inspect diff and manifest -> run validation -> leave a review comment",
    async () => {
      resetSession();
      setToken(mintToken("7a0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6b"));

      const container = freshContainer();
      const router = new Router(container, "projects");
      router.register({ name: "projects", render: (c) => renderProjects(c, router) });
      router.register({ name: "transform-run", render: (c) => renderTransformRun(c, router) });
      router.register({ name: "transform-diff", render: (c) => renderTransformDiff(c, router) });
      router.register({
        name: "transform-validate",
        render: (c) => renderTransformValidate(c, router),
      });
      router.register({
        name: "transform-evidence",
        render: (c) => renderTransformEvidence(c, router),
      });
      router.register({
        name: "transform-review",
        render: (c) => renderTransformReview(c, router),
      });

      // --- project ---------------------------------------------------
      await router.go("projects");
      const nameInput = container.querySelector<HTMLInputElement>("#name")!;
      nameInput.value = "E2E Transform Review";
      container
        .querySelector("[data-action='create-project']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await waitFor(() =>
        (container.querySelector("[data-slot='project-list']")!.textContent ?? "").includes(
          "E2E Transform Review",
        ),
      );
      container.querySelector<HTMLElement>("[data-action='select-project-for-transform']")!.click();

      // --- connect source + trigger transformation --------------------
      await waitFor(() => !!document.querySelector("[data-action='trigger-transformation']"));
      const runContainer = document.querySelector<HTMLElement>("#app")!;
      (runContainer.querySelector<HTMLInputElement>("#git_url")!).value = repoUrl;
      (runContainer.querySelector<HTMLInputElement>("#git_ref")!).value = "main";
      runContainer
        .querySelector("[data-action='trigger-transformation']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

      // --- inspect the diff and manifest: per-change status visibly
      // distinguished ------------------------------------------------
      await waitFor(() => !!document.querySelector("[data-slot='entries']"));
      const diffContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (diffContainer.querySelector("[data-slot='entries']")!.textContent ?? "").includes(
          "Applied",
        ),
      );
      const entryRow = diffContainer.querySelector<HTMLElement>("[data-slot='entries'] li")!;
      expect(entryRow.getAttribute("data-outcome")).toBe("APPLIED");
      expect(entryRow.textContent).toContain(ACL_DEPRECATED_RULE_ID);
      const unifiedDiffText = diffContainer.querySelector("[data-slot='unified-diff']")!.textContent!;
      expect(unifiedDiffText).toContain("aws_s3_bucket_acl");

      // --- run validation: per-check results, a failing check would
      // visibly block (this run's static re-parse check passes) --------
      diffContainer.querySelector<HTMLElement>("[data-action='view-validate']")!.click();
      await waitFor(() => !!document.querySelector("[data-action='run-validation']"));
      const validateContainer = document.querySelector<HTMLElement>("#app")!;
      validateContainer.querySelector<HTMLElement>("[data-action='run-validation']")!.click();
      await waitFor(() =>
        (validateContainer.querySelector("[data-slot='approved']")!.textContent ?? "").includes(
          "yes",
        ),
      );
      expect(
        validateContainer.querySelector<HTMLButtonElement>("[data-action='proceed']")!.disabled,
      ).toBe(false);

      // --- view the evidence record reference for this run ------------
      void router.go("transform-evidence");
      await waitFor(() => !!document.querySelector("[data-slot='evidence']"));
      const evidenceContainer = document.querySelector<HTMLElement>("#app")!;
      await waitFor(() =>
        (evidenceContainer.querySelector("[data-slot='evidence']")!.textContent ?? "").includes(
          "Package:",
        ),
      );
      const evidenceText = evidenceContainer.querySelector("[data-slot='evidence']")!.textContent!;
      expect(evidenceText).toContain("PASS");
      expect(evidenceText).toContain("none -- first package for this project");

      // --- leave a review comment: request changes, then approve,
      // blocked state visibly tracked ----------------------------------
      void router.go("transform-review");
      await waitFor(() => !!document.querySelector("[data-action='add-comment']"));
      const reviewContainer = document.querySelector<HTMLElement>("#app")!;
      (reviewContainer.querySelector<HTMLSelectElement>("#decision")!).value = "REQUEST_CHANGES";
      (reviewContainer.querySelector<HTMLTextAreaElement>("#body")!).value =
        "please double-check the replacement resource name";
      reviewContainer
        .querySelector("[data-action='add-comment']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await waitFor(() =>
        (reviewContainer.querySelector("[data-slot='blocked']")!.textContent ?? "").includes(
          "Blocked",
        ),
      );

      (reviewContainer.querySelector<HTMLSelectElement>("#decision")!).value = "APPROVE";
      (reviewContainer.querySelector<HTMLTextAreaElement>("#body")!).value = "looks good now";
      reviewContainer
        .querySelector("[data-action='add-comment']")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await waitFor(() =>
        (reviewContainer.querySelector("[data-slot='blocked']")!.textContent ?? "").includes(
          "Approved",
        ),
      );
      const commentsText = reviewContainer.querySelector("[data-slot='comments']")!.textContent!;
      expect(commentsText).toContain("please double-check the replacement resource name");
      expect(commentsText).toContain("looks good now");
    },
    60_000,
  );
});
