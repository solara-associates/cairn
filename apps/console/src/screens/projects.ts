import { api, ApiError, Project } from "../api";
import { onClick, onSubmit, setHtml, showError, formValue } from "../dom";
import { Router } from "../router";
import { setProjectId } from "../state";

function projectRow(project: Project): string {
  return `
    <li>
      <span>${project.name}</span>
      <button type="button" data-action="select-project" data-project-id="${project.project_id}">
        Select
      </button>
    </li>
  `;
}

export async function renderProjects(container: HTMLElement, router: Router): Promise<void> {
  setHtml(
    container,
    `
    <section>
      <h1>Projects</h1>
      <form data-action="create-project">
        <label for="name">New project name</label>
        <input id="name" name="name" required />
        <button type="submit">Create</button>
      </form>
      <ul data-slot="project-list"><li>Loading...</li></ul>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const listSlot = container.querySelector<HTMLElement>("[data-slot='project-list']");

  async function refresh(): Promise<void> {
    try {
      const projects = await api.listProjects();
      if (listSlot) {
        listSlot.innerHTML = projects.length
          ? projects.map(projectRow).join("")
          : "<li>No projects yet.</li>";
      }
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not load projects");
    }
  }

  onSubmit(container, "create-project", async (_event, form) => {
    const name = formValue(form, "name").trim();
    if (!name) {
      showError(container, "A project name is required.");
      return;
    }
    try {
      await api.createProject({ name });
      form.reset();
      await refresh();
    } catch (error) {
      showError(container, error instanceof ApiError ? error.message : "could not create project");
    }
  });

  onClick(container, "select-project", (_event, target) => {
    const projectId = target.dataset.projectId;
    if (projectId) {
      setProjectId(projectId);
      void router.go("connect");
    }
  });

  await refresh();
}
