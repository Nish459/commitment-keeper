import { dayDiff, plural, shortDay } from "./format";
import type { Commitment, Draft, PersonSummary } from "./types";

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

/** Lowercase and drop accents, so "zoë" is found by "zoe". */
const fold = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/** Every word typed must appear in the person's name or in the promise. An empty query matches all. */
export function matchesQuery(c: Commitment, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = fold(`${c.person} ${c.description}`);
  return words.every((word) => haystack.includes(word));
}

export const findPerson = (people: PersonSummary[], name: string) =>
  people.find((p) => p.name.toLowerCase() === name.toLowerCase());

/** What Kept remembers about someone, in plain sentences. Empty when there is nothing worth saying. */
export function historySentences(person: PersonSummary): string[] {
  const sentences: string[] = [];
  if (person.promises_by_me > 0) {
    sentences.push(
      `You've made ${person.name} ${plural(person.promises_by_me, "promise")} and kept ${person.kept_by_me}.`,
    );
  }
  if (person.emails_sent > 0 && person.last_emailed_at) {
    const subject = person.last_subject ?? "no subject";
    sentences.push(`Last emailed ${shortDay(person.last_emailed_at)}: \u201c${subject}\u201d.`);
  }
  if (person.open_to_me > 0) {
    sentences.push(`${person.name} still owes you ${plural(person.open_to_me, "thing")}.`);
  }
  return sentences;
}
