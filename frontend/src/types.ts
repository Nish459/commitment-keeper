export type Direction = "owed_by_me" | "owed_to_me";
export type CommitmentStatus = "open" | "in_progress" | "ready_for_review" | "done" | "dropped";
export type DraftStatus = "pending" | "approved" | "rejected";

export interface Commitment {
  id: number;
  direction: Direction;
  person: string;
  description: string;
  due: string | null;
  status: CommitmentStatus;
  source_id: string;
  source_quote: string;
  created_at: string;
}

export interface Draft {
  id: number;
  commitment_id: number;
  subject: string;
  body: string;
  sources: string[];
  status: DraftStatus;
  created_at: string;
  sent_to: string | null;
  sent_at: string | null;
}

export interface Capabilities {
  email: { enabled: boolean; sender: string; recipients: string[] };
  demo: boolean;
}

export interface AuditEvent {
  at: string;
  method: string;
  host: string;
  path: string;
  bytes_out: number;
  status_code: number | null;
  blocked: boolean;
  duration_ms: number;
}

export interface SweepResult {
  prepared: Draft[];
  failed: { commitment_id: number; description: string; reason: string }[];
  skipped: number;
  stopped: string | null;
}

export interface Concern {
  commitment_ids: number[];
  title: string;
  explanation: string;
  severity: "high" | "medium" | "low";
}

export interface WeekCheck {
  summary: string;
  concerns: Concern[];
  suggested_order: { commitment_id: number; reason: string }[];
  model_used: string | null;
}
