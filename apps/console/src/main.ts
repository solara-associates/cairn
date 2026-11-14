import { Router } from "./router";
import { renderSignIn } from "./screens/signin";
import { renderProjects } from "./screens/projects";
import { renderConnect } from "./screens/connect";
import { renderRun } from "./screens/run";
import { renderResults } from "./screens/results";
import { renderReport } from "./screens/report";
import { renderEvidence } from "./screens/evidence";

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
  router.register({ name: "sign-in", render: (c) => renderSignIn(c, router) });
  router.register({ name: "projects", render: (c) => renderProjects(c, router) });
  router.register({ name: "connect", render: (c) => renderConnect(c, router) });
  router.register({ name: "run", render: (c) => renderRun(c, router) });
  router.register({ name: "results", render: (c) => renderResults(c, router) });
  router.register({ name: "report", render: (c) => renderReport(c, router) });
  router.register({ name: "evidence", render: (c) => renderEvidence(c, router) });
  return router;
}

const journeyContainer = document.querySelector<HTMLElement>("#journey");
if (journeyContainer) {
  buildRouter(journeyContainer).start();
}

void checkApi();
