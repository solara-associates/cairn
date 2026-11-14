import { api, AssessmentRunSummary } from "../api";
import { setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

const TERMINAL_STATES = new Set(["COMPLETED", "FAILED"]);

/** Polls a queued run until it reaches a terminal state or ``maxAttempts``
 * is exhausted. A real deployment's ``BackgroundTasks`` run after the
 * response is sent, so the run may still be ``RUNNING``/``CHECKPOINTED``
 * the first few times this is called -- pure function, no DOM, so it is
 * directly unit-testable against a fake ``getRun``. */
export async function pollRun(
  getRun: () => Promise<AssessmentRunSummary>,
  options: { intervalMs?: number; maxAttempts?: number; onUpdate?: (run: AssessmentRunSummary) => void } = {},
): Promise<AssessmentRunSummary> {
  const intervalMs = options.intervalMs ?? 500;
  const maxAttempts = options.maxAttempts ?? 60;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const run = await getRun();
    options.onUpdate?.(run);
    if (TERMINAL_STATES.has(run.state)) {
      return run;
    }
    if (attempt < maxAttempts) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
  throw new Error(`assessment run did not reach a terminal state after ${maxAttempts} polls`);
}

function statusHtml(run: AssessmentRunSummary): string {
  return `
    <p>State: ${run.state}</p>
    <p>Coverage: ${(run.coverage * 100).toFixed(0)}%</p>
    <p>Completed stages: ${run.completed_stages.join(", ") || "none"}</p>
    <p>Pending stages: ${run.pending_stages.join(", ") || "none"}</p>
    ${run.failures.length ? `<p role="alert">Failures: ${run.failures.map((f) => `${f.stage}: ${f.error}`).join("; ")}</p>` : ""}
  `;
}

export async function renderRun(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const projectId = session.projectId;
  const runId = session.runId;
  if (!projectId || !runId) {
    void router.go("projects");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Assessment run</h1>
      <div data-slot="status"><p>Starting...</p></div>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );
  const statusSlot = container.querySelector<HTMLElement>("[data-slot='status']");

  try {
    const run = await pollRun(() => api.getAssessmentRun(projectId, runId), {
      onUpdate: (update) => {
        if (statusSlot) {
          statusSlot.innerHTML = statusHtml(update);
        }
      },
    });
    if (run.state === "COMPLETED") {
      void router.go("results");
    }
  } catch (error) {
    showError(container, error instanceof Error ? error.message : "the assessment run failed");
  }
}
