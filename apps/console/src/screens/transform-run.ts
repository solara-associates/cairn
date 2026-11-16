import { api, ApiError, RepositoryRef } from "../api";
import { onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { getSession, setTransformRunId } from "../state";

/** R3-07: the first screen of the diff review and validation console
 * (spec §16's R3-07 row) -- triggering a transformation run against a
 * project's connected source (721's `RepositorySourcePort`, 726's
 * engine). A Git ref and an uploaded archive are 721's own tagged union
 * (spec §16's R3-01 row); this screen offers both, never guessing which
 * one a caller means. */
export async function renderTransformRun(container: HTMLElement, router: Router): Promise<void> {
  const projectId = getSession().projectId;
  if (!projectId) {
    void router.go("projects");
    return;
  }

  setHtml(
    container,
    `
    <section>
      <h1>Trigger a transformation</h1>
      <p>Project: ${projectId}</p>

      <h2>Connected source</h2>
      <form data-action="trigger-transformation">
        <label for="source_kind">Source</label>
        <select id="source_kind" name="source_kind">
          <option value="GIT">Git repository</option>
          <option value="UPLOAD">Uploaded archive</option>
        </select>

        <div data-slot="git-fields">
          <label for="git_url">Repository URL (or local file:// path)</label>
          <input id="git_url" name="git_url" placeholder="https://example.test/repo.git" />
          <label for="git_ref">Ref (branch, tag or commit)</label>
          <input id="git_ref" name="git_ref" value="main" />
        </div>

        <div data-slot="upload-fields" hidden>
          <label for="archive_id">Uploaded archive id</label>
          <input id="archive_id" name="archive_id" />
        </div>

        <button type="submit">Scan and produce preview</button>
      </form>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const kindSelect = container.querySelector<HTMLSelectElement>("#source_kind");
  const gitFields = container.querySelector<HTMLElement>("[data-slot='git-fields']");
  const uploadFields = container.querySelector<HTMLElement>("[data-slot='upload-fields']");

  kindSelect?.addEventListener("change", () => {
    const isGit = kindSelect.value === "GIT";
    if (gitFields) gitFields.hidden = !isGit;
    if (uploadFields) uploadFields.hidden = isGit;
  });

  onSubmit(container, "trigger-transformation", async (_event, form) => {
    const kind = formValue(form, "source_kind");
    const repositoryRef: RepositoryRef =
      kind === "UPLOAD"
        ? { kind: "UPLOAD", archive_id: formValue(form, "archive_id").trim() }
        : { kind: "GIT", url: formValue(form, "git_url").trim(), ref: formValue(form, "git_ref").trim() };

    if (repositoryRef.kind === "GIT" && (!repositoryRef.url || !repositoryRef.ref)) {
      showError(container, "A repository URL and ref are both required.");
      return;
    }
    if (repositoryRef.kind === "UPLOAD" && !repositoryRef.archive_id) {
      showError(container, "An uploaded archive id is required.");
      return;
    }

    try {
      const run = await api.createTransformation(projectId, repositoryRef);
      setTransformRunId(run.run_id);
      void router.go("transform-diff");
    } catch (error) {
      showError(
        container,
        error instanceof ApiError ? error.message : "could not trigger the transformation",
      );
    }
  });
}
