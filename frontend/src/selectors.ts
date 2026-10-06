import { dayDiff } from "./format";
import type { Commitment, Draft } from "./types";

export const isClosed = (c: Commitment) => c.status === "done" || c.status === "dropped";

export const isOverdue = (c: Commitment, today: Date) =>
  !isClosed(c) && c.due !== null && dayDiff(c.due, today) < 0;

/** Drafts arrive newest first, so the first match is the latest. */
export const latestDraft = (drafts: Draft[], commitmentId: number): Draft | null =>
  drafts.find((d) => d.commitment_id === commitmentId) ?? null;

export function byDue(a: Commitment, b: Commitment): number {
  if (a.due === b.due) return a.id - b.id;
  if (!a.due) return 1;
  if (!b.due) return -1;
  return a.due < b.due ? -1 : 1;
}

export const directionLabel = (c: Commitment) => (c.direction === "owed_by_me" ? "You owe" : "Owes you");

export function shorten(text: string, max = 64): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

const SWEEP_HORIZON_DAYS = 3;

/** Promises the server's sweep would draft: open, mine, due soon, and not already rejected. */
export function sweepCandidates(commitments: Commitment[], drafts: Draft[], today: Date): Commitment[] {
  return commitments.filter(
    (c) =>
      c.direction === "owed_by_me" &&
      c.status === "open" &&
      c.due !== null &&
      dayDiff(c.due, today) <= SWEEP_HORIZON_DAYS &&
      latestDraft(drafts, c.id)?.status !== "rejected",
  );
}
