import { api, ApiError, AssessmentRunFile } from "../api";
import { onClick, onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { getSession, setRunId } from "../state";

const pendingFiles: AssessmentRunFile[] = [];

/** Resets module-level state so a fresh render (a new project, or the
 * end-to-end test re-running this screen for a second project) never
 * carries over a file queued for a previous project. */
function resetPendingFiles(): void {
  pendingFiles.length = 0;
}

function fileRow(file: AssessmentRunFile, index: number): string {
  return `<li>${file.source_format} (${file.content.length} bytes) <button type="button" data-action="remove-file" data-index="${index}">Remove</button></li>`;
}

export function renderConnect(container: HTMLElement, router: Router): void {
  resetPendingFiles();
  const projectId = getSession().projectId;
  if (!projectId) {
    void router.go("projects");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Connect a provider, or upload an estate file</h1>
      <p>Project: ${projectId}</p>

      <h2>Connect a provider (optional)</h2>
      <form data-action="connect-provider">
        <label for="provider">Provider</label>
        <input id="provider" name="provider" value="gcp" required />
        <label for="account_id">Account id</label>
        <input id="account_id" name="account_id" required />
        <label for="secret">Credential</label>
        <input id="secret" name="secret" type="password" required />
        <button type="submit">Connect</button>
      </form>
      <p data-slot="connection-status"></p>

      <h2>Upload a file</h2>
      <form data-action="add-file">
        <label for="source_format">Format</label>
        <select id="source_format" name="source_format">
          <option value="csv">csv</option>
          <option value="json">json</option>
          <option value="rvtools">rvtools</option>
          <option value="hvtools">hvtools</option>
          <option value="bom">bom</option>
        </select>
        <label for="content">File content</label>
        <textarea id="content" name="content" rows="5"></textarea>
        <button type="submit">Add file</button>
      </form>
      <ul data-slot="file-list"></ul>

      <button type="button" data-action="start-assessment">Start assessment</button>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const fileListSlot = container.querySelector<HTMLElement>("[data-slot='file-list']");
  function renderFileList(): void {
    if (fileListSlot) {
      fileListSlot.innerHTML = pendingFiles.map(fileRow).join("");
    }
  }

  onSubmit(container, "connect-provider", async (_event, form) => {
    const provider = formValue(form, "provider").trim();
    const accountId = formValue(form, "account_id").trim();
    const secret = formValue(form, "secret");
    if (!provider || !accountId || !secret) {
      showError(container, "Provider, account id and credential are all required.");
      return;
    }
    try {
      const connection = await api.createConnection(projectId, {
        provider,
        account_id: accountId,
        secret,
      });
      await api.validateConnection(projectId, connection.connection_id);
      const status = container.querySelector<HTMLElement>("[data-slot='connection-status']");
      if (status) {
        status.textContent = `Connected to ${connection.provider}:${connection.account_id} (read-only, validated).`;
      }
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not connect provider");
    }
  });

  onSubmit(container, "add-file", (_event, form) => {
    const sourceFormat = formValue(form, "source_format");
    const content = formValue(form, "content");
    if (!content.trim()) {
      showError(container, "File content is required.");
      return;
    }
    pendingFiles.push({ source_format: sourceFormat, content });
    form.reset();
    renderFileList();
  });

  onClick(container, "remove-file", (_event, target) => {
    const index = Number(target.dataset.index);
    if (!Number.isNaN(index)) {
      pendingFiles.splice(index, 1);
      renderFileList();
    }
  });

  onClick(container, "start-assessment", async () => {
    try {
      const run = await api.queueAssessmentRun(projectId, [...pendingFiles]);
      setRunId(run.run_id);
      void router.go("run");
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not start the assessment run");
    }
  });
}
