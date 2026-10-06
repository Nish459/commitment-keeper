const MS_PER_DAY = 86_400_000;
const weekday = new Intl.DateTimeFormat("en", { weekday: "short" });
const dayMonth = new Intl.DateTimeFormat("en", { day: "numeric", month: "short" });
const clock = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Parse YYYY-MM-DD as a local date (new Date(iso) would shift by timezone). */
export function parseDay(iso: string): Date {
  const [year = 0, month = 1, day = 1] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function toISO(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function startOfToday(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function dayDiff(iso: string, today: Date): number {
  return Math.round((parseDay(iso).getTime() - today.getTime()) / MS_PER_DAY);
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export const weekdayName = (date: Date) => weekday.format(date);
export const dayMonthName = (date: Date) => dayMonth.format(date);
/** A moment as a short day and month, like "6 Oct" is shown here as "Oct 6". */
export const shortDay = (iso: string) => dayMonth.format(new Date(iso));
export const clockTime = (iso: string) => clock.format(new Date(iso));

export function dueLabel(iso: string | null, today: Date): string {
  if (!iso) return "No date";
  const diff = dayDiff(iso, today);
  if (diff === 0) return "Due today";
  if (diff === 1) return "Due tomorrow";
  if (diff === -1) return "1 day overdue";
  if (diff < 0) return `${-diff} days overdue`;
  const date = parseDay(iso);
  return diff < 7 ? `Due ${weekday.format(date)}` : `Due ${dayMonth.format(date)}`;
}

export const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

export function formatBytes(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}
