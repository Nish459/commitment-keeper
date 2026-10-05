import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { AppContext, initialState, type Actions, type State } from "./state";
import type { Commitment, Draft } from "./types";

export const TODAY = new Date(2026, 9, 6);

export function makeActions(): Actions {
  return {
    select: vi.fn(),
    setFilter: vi.fn(),
    togglePerimeter: vi.fn(),
    closePerimeter: vi.fn(),
    openComposer: vi.fn(),
    closeComposer: vi.fn(),
    dismissToast: vi.fn(),
    prepare: vi.fn().mockResolvedValue(undefined),
    approve: vi.fn().mockResolvedValue(undefined),
    reject: vi.fn().mockResolvedValue(undefined),
    ingest: vi.fn().mockResolvedValue(undefined),
    copy: vi.fn().mockResolvedValue(undefined),
  };
}

export function commitment(overrides: Partial<Commitment> = {}): Commitment {
  return {
    id: 1,
    direction: "owed_by_me",
    person: "Priya",
    description: "send the comparison",
    due: "2026-10-09",
    status: "open",
    source_id: "standup",
    source_quote: "I will send it by Friday.",
    created_at: "2026-10-06T00:00:00Z",
    ...overrides,
  };
}

export function draft(overrides: Partial<Draft> = {}): Draft {
  return {
    id: 1,
    commitment_id: 1,
    subject: "Comparison",
    body: "Hi Priya,\n\nAcme sells widgets [1].\n\nSources:\n[1] https://www.acme.test/page",
    sources: ["https://www.acme.test/page"],
    status: "pending",
    created_at: "2026-10-06T00:00:00Z",
    ...overrides,
  };
}

export function renderApp(ui: ReactElement, state: Partial<State> = {}) {
  const actions = makeActions();
  const merged: State = { ...initialState, loading: false, ...state };
  const result = render(
    <AppContext.Provider value={{ state: merged, actions, today: TODAY }}>{ui}</AppContext.Provider>,
  );
  return { ...result, actions };
}
