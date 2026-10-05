import { describe, expect, it } from "vitest";

import { dayDiff, dueLabel, formatBytes, parseDay, plural, toISO } from "./format";

const TUE = new Date(2026, 9, 6);

describe("dates", () => {
  it("parses ISO days as local dates without timezone drift", () => {
    const day = parseDay("2026-10-09");
    expect([day.getFullYear(), day.getMonth(), day.getDate()]).toEqual([2026, 9, 9]);
    expect(toISO(day)).toBe("2026-10-09");
  });

  it("counts whole days from today", () => {
    expect(dayDiff("2026-10-09", TUE)).toBe(3);
    expect(dayDiff("2026-10-05", TUE)).toBe(-1);
  });

  it.each([
    [null, "No date"],
    ["2026-10-06", "Due today"],
    ["2026-10-07", "Due tomorrow"],
    ["2026-10-09", "Due Fri"],
    ["2026-10-20", "Due Oct 20"],
    ["2026-10-05", "1 day overdue"],
    ["2026-10-01", "5 days overdue"],
  ])("labels %s as %s", (iso, label) => {
    expect(dueLabel(iso, TUE)).toBe(label);
  });
});

describe("text helpers", () => {
  it("pluralizes", () => {
    expect(plural(1, "draft")).toBe("1 draft");
    expect(plural(2, "draft")).toBe("2 drafts");
  });

  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
  });
});
