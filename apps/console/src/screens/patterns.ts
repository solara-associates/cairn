import { api, ApiError, Pattern } from "../api";
import { onClick, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession, setDesignIds, setPatternId } from "../state";

function patternRow(pattern: Pattern): string {
  return `
    <li>
      <strong>${pattern.name}</strong> (${pattern.category})
      <p>${pattern.description}</p>
      <button type="button" data-action="select-pattern" data-pattern-id="${pattern.id}">
        Use this pattern
      </button>
    </li>
  `;
}

/** The first screen of the design journey (spec §16's R2-09 row):
 * selecting a pattern. Resets any design/plan already in the session so
 * starting a new design from here never carries over a previous one's
 * generated revision. */
export async function renderPatterns(container: HTMLElement, router: Router): Promise<void> {
  const projectId = getSession().projectId;
  if (!projectId) {
    void router.go("projects");
    return;
  }
  setDesignIds(null, null);

  setHtml(
    container,
    `
    <section>
      <h1>Design a target architecture</h1>
      <p>Project: ${projectId}</p>
      <h2>Choose a pattern</h2>
      <ul data-slot="pattern-list"><li>Loading...</li></ul>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  const listSlot = container.querySelector<HTMLElement>("[data-slot='pattern-list']");

  try {
    const patterns = await api.listPatterns();
    if (listSlot) {
      listSlot.innerHTML = patterns.length
        ? patterns.map(patternRow).join("")
        : "<li>No patterns in the catalogue.</li>";
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load patterns");
  }

  onClick(container, "select-pattern", (_event, target) => {
    const patternId = target.dataset.patternId;
    if (patternId) {
      setPatternId(patternId);
      void router.go("parameterize");
    }
  });
}
