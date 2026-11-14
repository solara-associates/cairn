import { getSession } from "./state";

let apiBase = "";

/** Override the API's origin -- used by the end-to-end test, which spawns
 * a real backend on an ephemeral port; the browser build leaves this at
 * "" and relies on same-origin/reverse-proxy routing instead. */
export function setApiBase(base: string): void {
  apiBase = base;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getSession().token;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${apiBase}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    const message =
      (typeof detail === "object" && detail !== null && "title" in detail
        ? String((detail as { title?: unknown }).title)
        : null) ?? `${method} ${path} failed with ${response.status}`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type Project = {
  project_id: string;
  tenant_id: string;
  name: string;
  customer_name: string | null;
  created_at: string;
  updated_at: string;
};

export type Connection = {
  connection_id: string;
  tenant_id: string;
  project_id: string;
  provider: string;
  account_id: string;
  scope: string;
  status: string;
  created_at: string;
  last_validated_at: string | null;
  revoked_at: string | null;
};

export type AssessmentRunFile = { source_format: string; content: string };

export type AssessmentRunSummary = {
  run_id: string;
  state: string;
  coverage: number;
  completed_stages: string[];
  pending_stages: string[];
  failures: { stage: string; error: string }[];
};

export type AssessmentRunResults = {
  run_id: string;
  coverage: AssessmentRunSummary;
  resources: unknown[] | null;
  workloads: Workload[] | null;
  dependencies: unknown[] | null;
  posture_assessment: unknown | null;
  cost_baseline: CostBaseline | null;
  tco_result: TcoResult | null;
  disposition_decisions: DispositionDecision[] | null;
};

export type Workload = {
  workload_id: string;
  name: string;
  environment: string;
  disposition: string | null;
};

export type CostBaseline = {
  currency: string;
  total_amount_minor: number;
  attributable_amount_minor: number;
  unallocated_amount_minor: number;
};

export type TcoResult = {
  scenario_id: string;
  currency: string;
  projected_total_minor: number;
  price_list_version: string;
};

export type DispositionDecision = {
  decision_id: string;
  workload_id: string;
  disposition: string;
  rationale: string;
  confidence: number;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
};

export type AssessmentReport = {
  run_id: string;
  run_coverage: { state: string; coverage: number };
  rendered_text: string;
  evidence_package_hash: string | null;
};

export type EvidencePackageResponse = {
  envelope: {
    package_id: string;
    payload_hash: string;
    previous_hash: string | null;
    signature: { key_id: string; algorithm: string; value: string };
  };
  report: AssessmentReport;
};

export const api = {
  createProject(input: { name: string; customer_name?: string }): Promise<Project> {
    return request("POST", "/v1/projects", input);
  },
  listProjects(): Promise<Project[]> {
    return request("GET", "/v1/projects");
  },
  createConnection(
    projectId: string,
    input: { provider: string; account_id: string; secret: string },
  ): Promise<Connection> {
    return request("POST", `/v1/projects/${projectId}/connections`, input);
  },
  validateConnection(projectId: string, connectionId: string): Promise<Connection> {
    return request(
      "POST",
      `/v1/projects/${projectId}/connections/${connectionId}/validate`,
    );
  },
  queueAssessmentRun(
    projectId: string,
    files: AssessmentRunFile[],
  ): Promise<AssessmentRunSummary> {
    return request("POST", `/v1/projects/${projectId}/assessment-runs`, { files });
  },
  getAssessmentRun(projectId: string, runId: string): Promise<AssessmentRunSummary> {
    return request("GET", `/v1/projects/${projectId}/assessment-runs/${runId}`);
  },
  getAssessmentRunResults(projectId: string, runId: string): Promise<AssessmentRunResults> {
    return request("GET", `/v1/projects/${projectId}/assessment-runs/${runId}/results`);
  },
  getAssessmentReport(projectId: string, runId: string): Promise<AssessmentReport> {
    return request("GET", `/v1/projects/${projectId}/assessment-runs/${runId}/report`);
  },
  acceptDecision(
    projectId: string,
    runId: string,
    decisionId: string,
  ): Promise<DispositionDecision> {
    return request(
      "POST",
      `/v1/projects/${projectId}/assessment-runs/${runId}/decisions/${decisionId}/accept`,
    );
  },
  rejectDecision(
    projectId: string,
    runId: string,
    decisionId: string,
    reason: string,
  ): Promise<DispositionDecision> {
    return request(
      "POST",
      `/v1/projects/${projectId}/assessment-runs/${runId}/decisions/${decisionId}/reject`,
      { reason },
    );
  },
  amendDecision(
    projectId: string,
    runId: string,
    decisionId: string,
    input: { disposition: string; rationale: string; confidence: number },
  ): Promise<DispositionDecision> {
    return request(
      "POST",
      `/v1/projects/${projectId}/assessment-runs/${runId}/decisions/${decisionId}/amend`,
      input,
    );
  },
  buildEvidencePackage(projectId: string, runId: string): Promise<EvidencePackageResponse> {
    return request(
      "POST",
      `/v1/projects/${projectId}/assessment-runs/${runId}/evidence-package`,
    );
  },
};
