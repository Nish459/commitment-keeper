import type { AuditEvent, Capabilities, Commitment, Draft, NewPromise, SweepResult, WeekCheck } from "./types";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the Kept server. Check that it's running.");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const detail = (body as { detail?: unknown }).detail;
    throw new ApiError(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

const put = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  commitments: () => request<Commitment[]>("/api/commitments"),
  addPromise: (promise: NewPromise) => post<Commitment>("/api/commitments", promise),
  drafts: () => request<Draft[]>("/api/drafts"),
  audit: () => request<AuditEvent[]>("/api/audit?limit=200"),
  unlockDemo: (code: string) => post<{ unlocked: boolean }>("/api/demo/access", { code }),
  allowlist: () => request<string[]>("/api/allowlist"),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  contacts: () => request<Record<string, string>>("/api/contacts"),
  profile: () => request<{ name: string }>("/api/profile"),
  saveProfile: (name: string) => put<{ name: string }>("/api/profile", { name }),
  ingest: (sourceId: string, text: string) =>
    post<Commitment[]>("/api/notes", { source_id: sourceId, text }),
  sweep: () => post<SweepResult>("/api/sweep"),
  weekCheck: () => post<WeekCheck>("/api/week-check"),
  prepare: (commitmentId: number) => post<Draft>(`/api/commitments/${commitmentId}/prepare`),
  updateDraft: (draftId: number, subject: string, body: string) =>
    put<Draft>(`/api/drafts/${draftId}`, { subject, body }),
  approve: (draftId: number, to?: string) =>
    post<Draft>(`/api/drafts/${draftId}/approve`, to ? { to } : undefined),
  reject: (draftId: number) => post<Draft>(`/api/drafts/${draftId}/reject`),
};
