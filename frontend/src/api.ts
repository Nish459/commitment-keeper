import type { AuditEvent, Commitment, Draft } from "./types";

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

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  commitments: () => request<Commitment[]>("/api/commitments"),
  drafts: () => request<Draft[]>("/api/drafts"),
  audit: () => request<AuditEvent[]>("/api/audit?limit=200"),
  allowlist: () => request<string[]>("/api/allowlist"),
  ingest: (sourceId: string, text: string) =>
    post<Commitment[]>("/api/notes", { source_id: sourceId, text }),
  prepare: (commitmentId: number) => post<Draft>(`/api/commitments/${commitmentId}/prepare`),
  approve: (draftId: number) => post<Draft>(`/api/drafts/${draftId}/approve`),
  reject: (draftId: number) => post<Draft>(`/api/drafts/${draftId}/reject`),
};
