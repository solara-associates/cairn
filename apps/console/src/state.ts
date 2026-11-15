export type Session = {
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  projectId: string | null;
  runId: string | null;
  patternId: string | null;
  designId: string | null;
  planId: string | null;
};

const session: Session = {
  token: null,
  refreshToken: null,
  expiresAt: null,
  projectId: null,
  runId: null,
  patternId: null,
  designId: null,
  planId: null,
};

export function getSession(): Session {
  return session;
}

export function setToken(
  token: string | null,
  refreshToken: string | null = null,
  expiresAt: number | null = null,
): void {
  session.token = token;
  session.refreshToken = refreshToken;
  session.expiresAt = expiresAt;
}

export function setProjectId(projectId: string | null): void {
  session.projectId = projectId;
}

export function setRunId(runId: string | null): void {
  session.runId = runId;
}

export function setPatternId(patternId: string | null): void {
  session.patternId = patternId;
}

/** Records a (re)generated design -- used by every screen downstream of
 * "generate" (results, roadmap, IaC preview, export) to know which design/
 * plan to read back. */
export function setDesignIds(designId: string | null, planId: string | null): void {
  session.designId = designId;
  session.planId = planId;
}

export function resetSession(): void {
  session.token = null;
  session.refreshToken = null;
  session.expiresAt = null;
  session.projectId = null;
  session.runId = null;
  session.patternId = null;
  session.designId = null;
  session.planId = null;
}
