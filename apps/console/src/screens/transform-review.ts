import { api, ApiError, ReviewComment, ReviewDecision, ReviewThread } from "../api";
import { onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { getSession } from "../state";

function commentRow(comment: ReviewComment): string {
  return `
    <li data-decision="${comment.decision}">
      <strong>${comment.reviewer_actor_id}</strong> -- ${comment.decision}
      <p>${comment.body}</p>
      <p><small>${comment.created_at}</small></p>
    </li>
  `;
}

/** R3-07: spec S16's own acceptance text, "Engineer can review, comment,
 * request changes" -- a lightweight annotation thread attached to the
 * run (`cairn_modules.transformation.review`), with the thread's own
 * ``blocked`` state shown honestly: a REQUEST_CHANGES comment visibly
 * blocks this run, not advisory text, until a later APPROVE clears it. */
export async function renderTransformReview(
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
      <h1>Review and comment</h1>
      <p>Run: ${runId}</p>
      <div data-slot="status"></div>
      <ul data-slot="comments"></ul>

      <form data-action="add-comment">
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
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const statusSlot = container.querySelector<HTMLElement>("[data-slot='status']");
  const commentsSlot = container.querySelector<HTMLElement>("[data-slot='comments']");

  function renderThread(thread: ReviewThread): void {
    if (statusSlot) {
      statusSlot.innerHTML = `
        <p data-slot="blocked">
          Status: ${thread.blocked ? "Blocked -- changes requested" : thread.reviewed ? "Approved" : "Not yet reviewed"}
        </p>
      `;
    }
    if (commentsSlot) {
      commentsSlot.innerHTML = thread.comments.map(commentRow).join("") || "<li>No comments yet.</li>";
    }
  }

  // Registered before the initial-load `await` below (not after) -- see
  // `transform-validate.ts`'s own identical comment: the delegated
  // listener must already be live by the time this function's promise
  // resolves, not only after a fetch that started afterwards finishes.
  onSubmit(container, "add-comment", async (_event, form) => {
    const decision = formValue(form, "decision") as ReviewDecision;
    const body = formValue(form, "body").trim();
    if (!body) {
      showError(container, "A comment body is required.");
      return;
    }
    try {
      const thread = await api.createReviewComment(runId, { decision, body });
      renderThread(thread);
      form.reset();
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not post the comment");
    }
  });

  try {
    const thread = await api.listReviewComments(runId);
    renderThread(thread);
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the review thread");
  }
}
