import { Router } from "./router";
import { isOidcCallback } from "./oidc";
import { renderSignIn } from "./screens/signin";
import { renderCallback } from "./screens/callback";
import { renderProjects } from "./screens/projects";
import { renderConnect } from "./screens/connect";
import { renderRun } from "./screens/run";
import { renderResults } from "./screens/results";
import { renderReport } from "./screens/report";
import { renderEvidence } from "./screens/evidence";
import { renderPatterns } from "./screens/patterns";
import { renderParameterize } from "./screens/parameterize";
import { renderDesignResults } from "./screens/design-results";
import { renderRoadmap } from "./screens/roadmap";
import { renderIac } from "./screens/iac";
import { renderDesignExport } from "./screens/design-export";

const statusElement = document.querySelector<HTMLParagraphElement>("#status");

type Health = {
  status: string;
  service: string;
  version: string;
};

async function checkApi(): Promise<void> {
  if (!statusElement) {
    return;
  }
  try {
    const response = await fetch("/healthz");
    if (!response.ok) {
      throw new Error(`health check returned ${response.status}`);
    }
    const health = (await response.json()) as Health;
    statusElement.textContent = `API ${health.status} (${health.service} ${health.version})`;
    statusElement.dataset.state = "ok";
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown error";
    statusElement.textContent = `API unavailable: ${detail}`;
    statusElement.dataset.state = "error";
  }
}

export function buildRouter(container: HTMLElement): Router {
  const router = new Router(container, "sign-in");
  router.register({ name: "sign-in", render: (c) => renderSignIn(c) });
  router.register({ name: "callback", render: (c) => renderCallback(c, router) });
  router.register({ name: "projects", render: (c) => renderProjects(c, router) });
  router.register({ name: "connect", render: (c) => renderConnect(c, router) });
  router.register({ name: "run", render: (c) => renderRun(c, router) });
  router.register({ name: "results", render: (c) => renderResults(c, router) });
  router.register({ name: "report", render: (c) => renderReport(c, router) });
  router.register({ name: "evidence", render: (c) => renderEvidence(c, router) });
  router.register({ name: "patterns", render: (c) => renderPatterns(c, router) });
  router.register({ name: "parameterize", render: (c) => renderParameterize(c, router) });
  router.register({ name: "design-results", render: (c) => renderDesignResults(c, router) });
  router.register({ name: "roadmap", render: (c) => renderRoadmap(c, router) });
  router.register({ name: "iac", render: (c) => renderIac(c, router) });
  router.register({ name: "design-export", render: (c) => renderDesignExport(c, router) });
  return router;
}

const journeyContainer = document.querySelector<HTMLElement>("#journey");
if (journeyContainer) {
  const router = buildRouter(journeyContainer);
  // The identity provider redirects back with `?code=...&state=...` (or
  // `?error=...`) on the plain path configured as `redirectUri` -- not a
  // hash route -- so this has to be detected before handing off to the
  // hash-based router.
  if (isOidcCallback(window.location.search)) {
    void router.go("callback");
  } else {
    router.start();
  }
}

void checkApi();
