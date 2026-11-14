export type Session = {
  token: string | null;
  projectId: string | null;
  runId: string | null;
};

const session: Session = { token: null, projectId: null, runId: null };

export function getSession(): Session {
  return session;
}

export function setToken(token: string | null): void {
  session.token = token;
}

export function setProjectId(projectId: string | null): void {
  session.projectId = projectId;
}

export function setRunId(runId: string | null): void {
  session.runId = runId;
}

export function resetSession(): void {
  session.token = null;
  session.projectId = null;
  session.runId = null;
}
