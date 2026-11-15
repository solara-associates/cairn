import { api, ApiError, Pattern, PatternParameter } from "../api";
import { onSubmit, setHtml, showError } from "../dom";
import { Router } from "../router";
import { getSession, setDesignIds } from "../state";

const DISPOSITIONS = ["REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE", "RETIRE", "RETAIN"];

function fieldId(name: string): string {
  return `param-${name}`;
}

function parameterField(parameter: PatternParameter, currentValue: unknown): string {
  const id = fieldId(parameter.name);
  const value = currentValue !== undefined ? currentValue : parameter.default;
  const requiredAttr = parameter.required ? "required" : "";
  let input: string;
  if (parameter.type === "enum") {
    const options = (parameter.allowed_values ?? [])
      .map((v) => `<option value="${v}" ${v === value ? "selected" : ""}>${v}</option>`)
      .join("");
    input = `<select id="${id}" name="${parameter.name}" ${requiredAttr}>${options}</select>`;
  } else if (parameter.type === "boolean") {
    input = `<input id="${id}" name="${parameter.name}" type="checkbox" ${value ? "checked" : ""} />`;
  } else if (parameter.type === "integer") {
    input = `<input id="${id}" name="${parameter.name}" type="number" step="1" value="${value ?? ""}" ${requiredAttr} />`;
  } else if (parameter.type === "string_list") {
    const joined = Array.isArray(value) ? value.join(", ") : "";
    input = `<input id="${id}" name="${parameter.name}" type="text" value="${joined}" placeholder="comma-separated" />`;
  } else {
    input = `<input id="${id}" name="${parameter.name}" type="text" value="${value ?? ""}" ${requiredAttr} />`;
  }
  return `
    <div>
      <label for="${id}">${parameter.name}${parameter.required ? " (required)" : ""}</label>
      ${input}
      <p>${parameter.description}</p>
    </div>
  `;
}

function readParameterValue(form: HTMLFormElement, parameter: PatternParameter): unknown {
  const element = form.elements.namedItem(parameter.name);
  if (parameter.type === "boolean") {
    return (element as HTMLInputElement | null)?.checked ?? false;
  }
  const raw = (element as HTMLInputElement | HTMLSelectElement | null)?.value ?? "";
  if (parameter.type === "integer") {
    return raw.trim() === "" ? null : Number(raw);
  }
  if (parameter.type === "string_list") {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }
  return raw.trim() === "" ? null : raw;
}

export async function renderParameterize(container: HTMLElement, router: Router): Promise<void> {
  const session = getSession();
  const projectId = session.projectId;
  if (!projectId) {
    void router.go("projects");
    return;
  }

  const regenerating = Boolean(session.designId);
  let pattern: Pattern | undefined;
  let currentParameters: Record<string, unknown> = {};

  try {
    const patterns = await api.listPatterns();
    if (regenerating && session.designId) {
      const bundle = await api.getDesign(session.designId);
      pattern = patterns.find((p) => p.id === bundle.design.pattern_id);
      currentParameters = Object.fromEntries(bundle.design.parameters);
    } else {
      if (!session.patternId) {
        void router.go("patterns");
        return;
      }
      pattern = patterns.find((p) => p.id === session.patternId);
    }
  } catch (error) {
    showError(container, error instanceof ApiError ? error.message : "could not load the pattern");
    return;
  }

  if (!pattern) {
    showError(container, "The selected pattern could not be found.");
    return;
  }

  const estateSection = regenerating
    ? ""
    : `
      <h2>Estate</h2>
      <p>One line per resource: <code>resource_id,provider,service,region</code></p>
      <textarea id="resources" name="resources" rows="4" placeholder="res-1,aws,s3,europe-west2"></textarea>

      <h2>Workload</h2>
      <label for="workload_name">Workload name</label>
      <input id="workload_name" name="workload_name" value="primary" />
      <label for="disposition">6R disposition</label>
      <select id="disposition" name="disposition">
        ${DISPOSITIONS.map((d) => `<option value="${d}">${d}</option>`).join("")}
      </select>
    `;

  setHtml(
    container,
    `
    <section>
      <h1>${regenerating ? "Regenerate design" : "Parameterize"}: ${pattern.name}</h1>
      <p>Pattern: ${pattern.id}${regenerating ? " (unchanged on regenerate)" : ""}</p>
      <form data-action="generate-design">
        ${
          regenerating
            ? ""
            : `
          <label for="target_provider">Target provider</label>
          <input id="target_provider" name="target_provider" value="gcp" required />
        `
        }
        <h2>Parameters</h2>
        ${pattern.parameters.map((p) => parameterField(p, currentParameters[p.name])).join("")}
        ${estateSection}
        <button type="submit">${regenerating ? "Regenerate" : "Generate design"}</button>
      </form>
      <p data-slot="error" role="alert" hidden></p>
    </section>
    `,
  );

  onSubmit(container, "generate-design", async (_event, form) => {
    if (!pattern) {
      return;
    }
    const parameters: Record<string, unknown> = {};
    for (const parameter of pattern.parameters) {
      parameters[parameter.name] = readParameterValue(form, parameter);
    }

    try {
      if (regenerating && session.designId) {
        const summary = await api.regenerateDesign(session.designId, parameters);
        setDesignIds(summary.design_id, summary.plan_id);
      } else {
        const resourcesRaw = (form.elements.namedItem("resources") as HTMLTextAreaElement | null)
          ?.value;
        const resources = (resourcesRaw ?? "")
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.length > 0)
          .map((line) => {
            const [resourceId, provider, service, region] = line.split(",").map((part) => part.trim());
            return { resource_id: resourceId, provider, service, region };
          });
        const workloadName =
          (form.elements.namedItem("workload_name") as HTMLInputElement | null)?.value || "primary";
        const disposition =
          (form.elements.namedItem("disposition") as HTMLSelectElement | null)?.value ?? "REHOST";
        const workloads = resources.length
          ? [
              {
                workload_id: "wl-1",
                name: workloadName,
                resource_ids: resources.map((r) => r.resource_id),
              },
            ]
          : [];
        const decisions = resources.length ? [{ workload_id: "wl-1", disposition }] : [];
        const targetProvider =
          (form.elements.namedItem("target_provider") as HTMLInputElement | null)?.value || "gcp";
        const summary = await api.createDesign(projectId, {
          pattern_id: pattern.id,
          target_provider: targetProvider,
          parameters,
          resources,
          workloads,
          decisions,
        });
        setDesignIds(summary.design_id, summary.plan_id);
      }
      void router.go("design-results");
    } catch (error) {
      showError(
        container,
        error instanceof ApiError ? error.message : "could not generate the design",
      );
    }
  });
}
