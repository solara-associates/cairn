import {
  api,
  ApiError,
  MutationClass,
  PlanApprovalThread,
  PlanApprovalView,
  RecoveryStrategy,
  ReviewComment,
  ReviewDecision,
} from "../api";
import { onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { getSession, setPlanRevisionId } from "../state";

/** 792/R4-05: spec §2.4's own acceptance text, quoted verbatim in this
 * unit's brief -- "R4-05's console shows the approver the exact
 * revision: the diff, the mutation class, the recovery plan (rollback
 * or compensation contract, ADR-010), and the evidence that will be
 * captured. Nothing is approved from a summary -- the approver sees what
 * will actually run." No cloud -- the server orchestrates 787's
 * Terraform plan revision against the fake provider adapter only. */

function diffRow(entry: PlanApprovalView["revision"]["diff"][number]): string {
  const label = entry.action === "GAP" ? "Gap -- no resource planned" : "Create";
  return `
    <li data-action="${entry.action}">
      <strong>${entry.resource_id}</strong> -- ${label}${entry.approximate ? " (approximate mapping)" : ""}
      <p>${entry.source_provider}/${entry.source_service} -> ${entry.target_provider}${entry.target_service ? `/${entry.target_service}` : ""}</p>
      ${entry.detail ? `<p>${entry.detail}</p>` : ""}
    </li>
  `;
}

function commentRow(comment: ReviewComment): string {
  return `
    <li data-decision="${comment.decision}">
      <strong>${comment.reviewer_actor_id}</strong> -- ${comment.decision}
      <p>${comment.body}</p>
      <p><small>${comment.created_at}</small></p>
    </li>
  `;
}

const RISK_TIER_LABEL: Record<string, string> = {
  TIER_1: "Tier 1 -- reversible, one approver",
  TIER_2: "Tier 2 -- compensatable, two approvers (separation of duties)",
  TIER_3: "Tier 3 -- irreversible, explicit risk acceptance required",
};

function renderView(container: HTMLElement, view: PlanApprovalView): void {
  const revision = view.revision;
  const summarySlot = container.querySelector<HTMLElement>("[data-slot='revision']");
  if (summarySlot) {
    summarySlot.innerHTML = `
      <p>Revision: ${revision.revision_id} (number ${revision.revision_number})</p>
      <p>Content hash: ${revision.content_hash}</p>
      <p>Mutation class: <strong>${revision.mutation_class}</strong></p>
      <p>Risk tier: ${view.risk_tier ? RISK_TIER_LABEL[view.risk_tier] ?? view.risk_tier : "none -- no external recovery required"}</p>
      <p>Reversible: ${revision.reversible ? "yes" : "no"}</p>
    `;
  }
  const diffSlot = container.querySelector<HTMLElement>("[data-slot='diff']");
  if (diffSlot) {
    diffSlot.innerHTML = revision.diff.map(diffRow).join("") || "<li>No resources in this plan.</li>";
  }
  const recoverySlot = container.querySelector<HTMLElement>("[data-slot='recovery-plan']");
  if (recoverySlot) {
    recoverySlot.innerHTML = view.recovery_plan
      ? `
        <p>Strategy: <strong>${view.recovery_plan.strategy}</strong></p>
        <p>Plan reference: ${view.recovery_plan.plan_ref}</p>
        <p>Preconditions: ${view.recovery_plan.preconditions}</p>
        <p>Authority: ${view.recovery_plan.authority}</p>
        <p>Failure handling: ${view.recovery_plan.failure_handling}</p>
      `
      : `<p data-slot="no-recovery-plan">No recovery plan recorded yet -- this mutation cannot be approved from this console until one is.</p>`;
  }
  const evidenceSlot = container.querySelector<HTMLElement>("[data-slot='evidence']");
  if (evidenceSlot) {
    evidenceSlot.textContent = view.evidence_to_capture;
  }
  renderApproval(container, view.approval);
}

function renderApproval(container: HTMLElement, approval: PlanApprovalThread): void {
  const statusSlot = container.querySelector<HTMLElement>("[data-slot='approval-status']");
  if (statusSlot) {
    statusSlot.innerHTML = `
      <p data-slot="blocked">
        Status: ${approval.blocked ? "Blocked -- changes requested" : approval.reviewed ? "Approved" : "Not yet reviewed"}
      </p>
    `;
  }
  const commentsSlot = container.querySelector<HTMLElement>("[data-slot='comments']");
  if (commentsSlot) {
    commentsSlot.innerHTML = approval.comments.map(commentRow).join("") || "<li>No decisions yet.</li>";
  }
}

export async function renderPlanApproval(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const designId = session.designId;
  if (!designId) {
    void router.go("patterns");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Approval and execution console</h1>
      <p>Design: ${designId}</p>

      <form data-action="propose-plan">
        <h2>Propose this design's Terraform plan for approval</h2>
        <label for="mutation_class">Mutation class</label>
        <select id="mutation_class" name="mutation_class">
          <option value="REVERSIBLE_EXTERNAL_MUTATION">Reversible external mutation</option>
          <option value="COMPENSATABLE_EXTERNAL_MUTATION">Compensatable external mutation</option>
          <option value="IRREVERSIBLE_EXTERNAL_MUTATION">Irreversible external mutation</option>
        </select>

        <h3>Recovery plan (rollback or compensation contract, ADR-010)</h3>
        <p><small>Leave every field below blank to propose with no recovery plan recorded yet.</small></p>
        <label for="strategy">Strategy</label>
        <select id="strategy" name="strategy">
          <option value="ROLLBACK">Rollback</option>
          <option value="COMPENSATE">Compensate</option>
          <option value="ACCEPT_IRREVERSIBLE">Accept irreversible (no rollback promise)</option>
        </select>
        <label for="plan_ref">Plan reference</label>
        <input id="plan_ref" name="plan_ref" />
        <label for="preconditions">Preconditions</label>
        <input id="preconditions" name="preconditions" />
        <label for="authority">Authority</label>
        <input id="authority" name="authority" />
        <label for="evidence">Evidence to be captured</label>
        <input id="evidence" name="evidence" />
        <label for="failure_handling">Failure handling</label>
        <input id="failure_handling" name="failure_handling" />

        <button type="submit">Propose for approval</button>
      </form>

      <div data-slot="console" hidden>
        <h2>Exact revision</h2>
        <div data-slot="revision"></div>
        <h3>Diff</h3>
        <ul data-slot="diff"></ul>

        <h2>Recovery plan</h2>
        <div data-slot="recovery-plan"></div>

        <h2>Evidence that will be captured</h2>
        <p data-slot="evidence"></p>

        <h2>Approve, comment or request changes</h2>
        <div data-slot="approval-status"></div>
        <ul data-slot="comments"></ul>
        <form data-action="decide">
          <label for="decision">Decision</label>
          <select id="decision" name="decision">
            <option value="COMMENT">Comment only</option>
            <option value="REQUEST_CHANGES">Request changes</option>
            <option value="APPROVE">Approve</option>
          </select>
          <label for="body">Comment</label>
          <textarea id="body" name="body" rows="3" required></textarea>
          <button type="submit">Post</button>
        </form>
      </div>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const consoleSlot = container.querySelector<HTMLElement>("[data-slot='console']");

  // Registered before any `await` below -- the delegated listeners must
  // already be live by the time this function's own promise resolves,
  // the same discipline `transform-review.ts`/`transform-validate.ts`
  // already follow.
  onSubmit(container, "propose-plan", async (_event, form) => {
    const mutationClass = formValue(form, "mutation_class") as MutationClass;
    const strategy = formValue(form, "strategy") as RecoveryStrategy;
    const planRef = formValue(form, "plan_ref").trim();
    const preconditions = formValue(form, "preconditions").trim();
    const authority = formValue(form, "authority").trim();
    const evidence = formValue(form, "evidence").trim();
    const failureHandling = formValue(form, "failure_handling").trim();
    const recoveryFields = [planRef, preconditions, authority, evidence, failureHandling];
    const anyRecoveryFieldFilled = recoveryFields.some((value) => value.length > 0);
    if (anyRecoveryFieldFilled && recoveryFields.some((value) => value.length === 0)) {
      showError(container, "A recovery plan needs every field filled in, or none at all.");
      return;
    }

    try {
      const view = await api.createPlanApproval(designId, {
        mutation_class: mutationClass,
        ...(anyRecoveryFieldFilled
          ? {
              compensation: {
                strategy,
                plan_ref: planRef,
                preconditions,
                authority,
                evidence,
                failure_handling: failureHandling,
              },
            }
          : {}),
      });
      setPlanRevisionId(view.revision.revision_id);
      if (consoleSlot) {
        consoleSlot.hidden = false;
      }
      renderView(container, view);
    } catch (error) {
      showError(
        container,
        error instanceof ApiError ? error.message : "could not propose this plan for approval",
      );
    }
  });

  onSubmit(container, "decide", async (_event, form) => {
    const revisionId = getSession().planRevisionId;
    if (!revisionId) {
      return;
    }
    const decision = formValue(form, "decision") as ReviewDecision;
    const body = formValue(form, "body").trim();
    if (!body) {
      showError(container, "A comment body is required.");
      return;
    }
    try {
      const approval = await api.createApprovalDecision(revisionId, { decision, body });
      renderApproval(container, approval);
      form.reset();
    } catch (error) {
      showError(
        container,
        error instanceof ApiError ? error.message : "could not record this decision",
      );
    }
  });
}
