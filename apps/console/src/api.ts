import { loadConfig } from "./config";
import { refreshAccessToken } from "./oidc";
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

// Refresh a little ahead of actual expiry so a request doesn't race the
// token dying mid-flight.
const REFRESH_SKEW_MS = 30_000;

async function ensureFreshToken(): Promise<void> {
  const session = getSession();
  if (
    !session.token ||
    !session.refreshToken ||
    !session.expiresAt ||
    Date.now() < session.expiresAt - REFRESH_SKEW_MS
  ) {
    return;
  }
  const config = await loadConfig();
  await refreshAccessToken(config.oidc, session.refreshToken);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  await ensureFreshToken();
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

// --- R2-09: design console (pattern select -> parameterize -> generate ->
// regenerate -> inspect caveats -> export) ---

export type PatternParameter = {
  name: string;
  type: "string" | "integer" | "boolean" | "enum" | "string_list";
  description: string;
  required: boolean;
  default: unknown;
  allowed_values: string[] | null;
};

export type Pattern = {
  id: string;
  name: string;
  category: string;
  description: string;
  parameters: PatternParameter[];
};

export type ResourceInput = {
  resource_id: string;
  provider: string;
  service: string;
  account_id?: string;
  region?: string;
  resource_type?: string;
  native_id?: string | null;
  name?: string | null;
};

export type WorkloadInput = {
  workload_id: string;
  name: string;
  environment?: string;
  resource_ids: string[];
};

export type DecisionInput = {
  workload_id: string;
  disposition: string;
  rationale?: string;
  confidence?: number;
};

export type CreateDesignRequest = {
  pattern_id: string;
  target_provider: string;
  parameters: Record<string, unknown>;
  resources: ResourceInput[];
  workloads: WorkloadInput[];
  decisions: DecisionInput[];
};

/** A target-model resource's resolution outcome, visibly distinguished:
 * ``marker`` is always exactly one of ``EXACT``/``APPROXIMATE``/
 * ``UNAVAILABLE``/``UNRESOLVED`` (704's own distinct-marker rule) --
 * never collapsed into a single generic "not exact" state. */
export type ResourceMarker = "EXACT" | "APPROXIMATE" | "UNAVAILABLE" | "UNRESOLVED";

export type ResourceResolution = {
  shape_id: string;
  source_provider: string;
  source_service: string;
  target_provider: string;
  target_service: string | null;
  marker: ResourceMarker;
  detail: string | null;
};

export type DesignSummary = {
  design_id: string;
  plan_id: string;
  revision_number: number;
  content_hash: string;
  pattern_id: string;
  target_provider: string;
  parameters: Record<string, unknown>;
  resources: ResourceResolution[];
  wave_count: number;
  blocked_workload_ids: string[];
};

export type DesignRevisionSummary = {
  revision_id: string;
  revision_number: number;
  content_hash: string;
  created_at: string;
  parameters: Record<string, unknown>;
};

export type VersionStamp = {
  pattern_catalogue_version: string;
  mapping_release_version: string;
  target_provider: string;
};

export type DesignExportBundle = {
  tenant_id: string;
  project_id: string;
  design_id: string;
  design: {
    design_id: string;
    revision_id: string;
    revision_number: number;
    content_hash: string;
    pattern_id: string;
    parameters: [string, unknown][];
    versions: VersionStamp;
  };
  diagram: {
    artefact_id: string;
    revision_number: number;
    content_hash: string;
    shape_count: number;
    unresolved_shape_ids: string[];
    versions: VersionStamp;
  };
  plan: {
    plan_id: string;
    revision_number: number;
    content_hash: string;
    wave_count: number;
    workload_count: number;
    blocked_workload_ids: string[];
    versions: VersionStamp;
  };
  iac: {
    artefact_id: string;
    revision_number: number;
    content_hash: string;
    gap_resource_ids: string[];
    versions: VersionStamp;
  };
  version_stamps_consistent: boolean;
};

export type DiagramResponse = {
  artefact_id: string;
  kind: string;
  revision_number: number;
  content_hash: string;
  rendered_content: string;
  shapes: ResourceResolution[];
};

export type IacResourcePlan = {
  resource_id: string;
  source_provider: string;
  source_service: string;
  target_provider: string;
  target_service: string | null;
  status: "PLANNED" | "GAP";
  approximate: boolean;
  detail: string | null;
};

export type IacPreview = {
  artefact_id: string;
  revision_number: number;
  content_hash: string;
  disclaimer: string;
  rendered_content: string;
  gap_resource_ids: string[];
  resources: IacResourcePlan[];
};

export type PlanRevision = {
  plan_id: string;
  revision_id: string;
  revision_number: number;
  content_hash: string;
  wave_count: number;
  waves: {
    wave_number: number;
    workloads: {
      workload_id: string;
      disposition: string | null;
      constraints: { kind: string; detail: string }[];
    }[];
  }[];
  blocked_workload_ids: string[];
};

// --- R3-07: diff review and validation console (trigger transformation
// -> inspect diff/manifest -> run validation -> leave a review comment)
// ---

export type RepositoryRef =
  | { kind: "GIT"; url: string; ref: string }
  | { kind: "UPLOAD"; archive_id: string };

/** A manifest entry's own outcome -- visibly distinguished, never
 * collapsed into a single generic "changed"/"not changed" state (same
 * discipline R2-09's `ResourceMarker` already uses for its own four
 * distinct markers). */
export type ManifestOutcome = "APPLIED" | "SKIPPED" | "UNSUPPORTED";

export type ManifestEdit = {
  start_byte: number;
  end_byte: number;
  start_line: number;
  end_line: number;
  replacement: string;
};

export type ManifestEntry = {
  rule_id: string;
  outcome: ManifestOutcome;
  reason: string | null;
  edits: ManifestEdit[];
  detector_version: string;
  pattern_version: string;
  patcher_version: string;
  mapping_release_version: string | null;
};

export type ValidationResult = {
  check_id: string;
  passed: boolean;
  reason: string | null;
};

export type ValidationSummary = {
  run_id: string;
  approved: boolean;
  results: ValidationResult[];
};

export type ReviewDecision = "COMMENT" | "REQUEST_CHANGES" | "APPROVE";

export type ReviewComment = {
  reviewer_actor_id: string;
  decision: ReviewDecision;
  body: string;
  created_at: string;
};

export type ReviewThread = {
  run_id: string;
  blocked: boolean;
  reviewed: boolean;
  comments: ReviewComment[];
};

export type TransformationRunSummary = {
  run_id: string;
  project_id: string;
  run_number: number;
  source_file_ids: string[];
  applied_count: number;
  skipped_count: number;
  unsupported_count: number;
  created_by: string;
  created_at: string;
  validation: ValidationSummary | null;
  review: ReviewThread | null;
};

export type FileDiff = {
  source_file_id: string;
  changed: boolean;
  unified_diff: string;
  original_content: string;
  rendered_content: string;
  applied_count: number;
  skipped_count: number;
  unsupported_count: number;
  entries: ManifestEntry[];
};

export type TransformationDiff = {
  run_id: string;
  source_file_ids: string[];
  applied_count: number;
  skipped_count: number;
  unsupported_count: number;
  files: FileDiff[];
};

export type TransformationEvidencePackageResponse = {
  envelope: {
    package_id: string;
    payload_hash: string;
    previous_hash: string | null;
    outcome: string;
    outputs: { kind: string; ref: string; hash: string }[];
    signature: { key_id: string; algorithm: string; value: string };
  };
  report: TransformationRunSummary;
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
  listPatterns(): Promise<Pattern[]> {
    return request("GET", "/v1/patterns");
  },
  createDesign(projectId: string, input: CreateDesignRequest): Promise<DesignSummary> {
    return request("POST", `/v1/projects/${projectId}/designs`, input);
  },
  regenerateDesign(
    designId: string,
    parameters: Record<string, unknown>,
  ): Promise<DesignSummary> {
    return request("POST", `/v1/designs/${designId}/regenerate`, { parameters });
  },
  listDesignRevisions(designId: string): Promise<DesignRevisionSummary[]> {
    return request("GET", `/v1/designs/${designId}/revisions`);
  },
  getDesignRevision(designId: string, revisionNumber: number): Promise<DesignExportBundle> {
    return request("GET", `/v1/designs/${designId}/revisions/${revisionNumber}`);
  },
  getDesign(designId: string): Promise<DesignExportBundle> {
    return request("GET", `/v1/designs/${designId}`);
  },
  getDesignDiagram(designId: string): Promise<DiagramResponse> {
    return request("GET", `/v1/designs/${designId}/diagram`);
  },
  getDesignIac(designId: string): Promise<IacPreview> {
    return request("GET", `/v1/designs/${designId}/iac`);
  },
  getPlanRevision(planId: string, revisionNumber: number): Promise<PlanRevision> {
    return request("GET", `/v1/plans/${planId}/revisions/${revisionNumber}`);
  },
  createTransformation(
    projectId: string,
    repositoryRef: RepositoryRef,
  ): Promise<TransformationRunSummary> {
    return request("POST", `/v1/projects/${projectId}/transformations`, {
      repository_ref: repositoryRef,
    });
  },
  getTransformation(runId: string): Promise<TransformationRunSummary> {
    return request("GET", `/v1/transformations/${runId}`);
  },
  getTransformationDiff(runId: string): Promise<TransformationDiff> {
    return request("GET", `/v1/transformations/${runId}/diff`);
  },
  validateTransformation(runId: string): Promise<ValidationSummary> {
    return request("POST", `/v1/transformations/${runId}:validate`);
  },
  buildTransformationEvidencePackage(
    runId: string,
  ): Promise<TransformationEvidencePackageResponse> {
    return request("POST", `/v1/transformations/${runId}/evidence-package`);
  },
  listReviewComments(runId: string): Promise<ReviewThread> {
    return request("GET", `/v1/transformations/${runId}/review-comments`);
  },
  createReviewComment(
    runId: string,
    input: { decision: ReviewDecision; body: string },
  ): Promise<ReviewThread> {
    return request("POST", `/v1/transformations/${runId}/review-comments`, input);
  },
};
