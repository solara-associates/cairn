import { api, ApiError, ValidationResult, ValidationSummary } from "../api";
import { onClick, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

function resultRow(result: ValidationResult): string {
  return `
    <li data-passed="${result.passed}">
      <strong>${result.check_id}</strong> --
      <span data-slot="result-label">${result.passed ? "Pass" : "Fail"}</span>
      ${result.reason ? `<p>${result.reason}</p>` : ""}
    </li>
  `;
}

/** R3-07: triggering 729's validation and showing per-check pass/fail
 * results, with a failing check visibly blocking further progress --
 * 729's own blocking, not advisory, wiring (`require_validation_
 * passed`), reflected honestly here: the "proceed to review" action is
 * disabled, not merely discouraged, while `approved` is false. */
export async function renderTransformValidate(
  container: HTMLElement,
  router: Router,
): Promise<void> {
  const session = getSession();
  const runId = session.transformRunId;
  if (!runId) {
    void router.go("transform-run");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Validation</h1>
      <p>Run: ${runId}</p>
      <button type="button" data-action="run-validation">Run validation</button>
      <div data-slot="outcome"></div>
      <ul data-slot="results"></ul>
      <button type="button" data-action="proceed" disabled>
        Proceed to review
      </button>
      <p data-slot="blocked-notice" hidden>
        Validation failed -- fix the reported checks before this run can proceed to review.
      </p>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const outcomeSlot = container.querySelector<HTMLElement>("[data-slot='outcome']");
  const resultsSlot = container.querySelector<HTMLElement>("[data-slot='results']");
  const proceedButton = container.querySelector<HTMLButtonElement>("[data-action='proceed']");
  const blockedNotice = container.querySelector<HTMLElement>("[data-slot='blocked-notice']");

  function renderOutcome(summary: ValidationSummary): void {
    if (outcomeSlot) {
      outcomeSlot.innerHTML = `<p data-slot="approved">Approved: ${summary.approved ? "yes" : "no"}</p>`;
    }
    if (resultsSlot) {
      resultsSlot.innerHTML = summary.results.map(resultRow).join("") || "<li>No checks ran.</li>";
    }
    // A failing check visibly blocks further progress -- the button is
    // disabled, not merely labelled, while approved is false.
    if (proceedButton) {
      proceedButton.disabled = !summary.approved;
    }
    if (blockedNotice) {
      blockedNotice.hidden = summary.approved;
    }
  }

  // Registered before the initial-load `await` below (not after) -- the
  // delegated listener must already be live by the time this function's
  // own promise resolves and a caller (a route transition, or this
  // screen's own e2e test) can observe the button in the DOM and click
  // it; attaching it after an `await` would leave a window where the
  // button exists but nothing is listening yet.
  onClick(container, "run-validation", async () => {
    try {
      const summary = await api.validateTransformation(runId);
      renderOutcome(summary);
    } catch (error) {
      showError(
        container,
        error instanceof ApiError ? error.message : "could not run validation",
      );
    }
  });

  onClick(container, "proceed", () => {
    if (proceedButton?.disabled) {
      return;
    }
    void router.go("transform-review");
  });

  try {
    const existing = await api.getTransformation(runId);
    if (existing.validation) {
      renderOutcome(existing.validation);
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the run");
  }
}
