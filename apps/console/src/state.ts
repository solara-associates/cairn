export type Session = {
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  projectId: string | null;
  runId: string | null;
};

const session: Session = {
  token: null,
  refreshToken: null,
  expiresAt: null,
  projectId: null,
  runId: null,
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

export function resetSession(): void {
  session.token = null;
  session.refreshToken = null;
  session.expiresAt = null;
  session.projectId = null;
  session.runId = null;
}
