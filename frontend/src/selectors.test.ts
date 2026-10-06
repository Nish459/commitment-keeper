import { describe, expect, it } from "vitest";

import { matchesQuery } from "./selectors";
import { commitment } from "./testing";

const promise = commitment({ person: "Zoë", description: "Send the Q4 roadmap" });

describe("matchesQuery", () => {
  it.each([
    ["", true],
    ["   ", true],
    ["zoe", true],
    ["ZOË", true],
    ["roadmap", true],
    ["q4 road", true],
    ["zoe roadmap", true],
    ["roadmap zoe", true],
    ["marcus", false],
    ["zoe budget", false],
    ["quarterly", false],
  ])("%j -> %s", (query, expected) => {
    expect(matchesQuery(promise, query)).toBe(expected);
  });
});
