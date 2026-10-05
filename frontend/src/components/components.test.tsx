import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { commitment, draft, renderApp, TODAY } from "../testing";
import { Detail } from "./Detail";
import { Hero } from "./Hero";
import { Ledger } from "./Ledger";
import { DraftBody } from "./RichText";
import { buildColumns } from "./Timeline";

describe("Hero", () => {
  it("invites the first note when nothing is tracked", async () => {
    const { actions } = renderApp(<Hero />);
    expect(screen.getByRole("heading", { name: "Nothing to keep yet." })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try a sample note" }));
    expect(actions.openComposer).toHaveBeenCalledWith({ sample: true });
  });

  it("leads with drafts waiting for approval", () => {
    renderApp(<Hero />, {
      commitments: [commitment({ status: "ready_for_review" })],
      drafts: [draft()],
    });
    expect(screen.getByRole("heading", { name: "1 draft ready for your approval." })).toBeInTheDocument();
  });

  it("offers to prepare the next promise when nothing is ready", async () => {
    const { actions } = renderApp(<Hero />, { commitments: [commitment()] });
    expect(screen.getByRole("heading").textContent).toMatch(/^Next up: send the comparison, due fri\.$/);
    await userEvent.click(screen.getByRole("button", { name: "Research and draft" }));
    expect(actions.prepare).toHaveBeenCalledWith(1);
  });
});

describe("Timeline columns", () => {
  it("puts promises on their day, overdue first, and drops closed past items", () => {
    const columns = buildColumns(
      [
        commitment({ id: 1, due: "2026-10-09" }),
        commitment({ id: 2, due: "2026-10-04" }),
        commitment({ id: 3, due: "2026-10-04", status: "done" }),
        commitment({ id: 4, due: null }),
        commitment({ id: 5, due: "2026-11-30" }),
      ],
      TODAY,
    );
    expect(columns[0]?.key).toBe("overdue");
    expect(columns[0]?.items.map((c) => c.id)).toEqual([2]);
    expect(columns.find((c) => c.key === "2026-10-09")?.items.map((c) => c.id)).toEqual([1]);
    expect(columns.find((c) => c.key === "later")?.items.map((c) => c.id)).toEqual([5]);
    expect(columns.find((c) => c.key === "undated")?.items.map((c) => c.id)).toEqual([4]);
    expect(columns.flatMap((c) => c.items).map((c) => c.id)).not.toContain(3);
  });
});

describe("Ledger", () => {
  const commitments = [
    commitment({ id: 1, person: "Priya" }),
    commitment({ id: 2, person: "Priya", direction: "owed_to_me", description: "share the deck" }),
    commitment({ id: 3, person: "Marcus", status: "done", description: "review the doc" }),
  ];

  it("groups by person and filters", async () => {
    const { actions } = renderApp(<Ledger />, { commitments });
    expect(screen.getByRole("heading", { name: /Priya/ })).toBeInTheDocument();
    expect(screen.queryByText("review the doc")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Kept/ }));
    expect(actions.setFilter).toHaveBeenCalledWith("done");
  });

  it("selects a promise from its row", async () => {
    const { actions } = renderApp(<Ledger />, { commitments });
    await userEvent.click(screen.getByRole("button", { name: /share the deck/ }));
    expect(actions.select).toHaveBeenCalledWith(2, { scroll: true });
  });
});

describe("Detail", () => {
  it("shows the draft with approve and reject for a pending draft", async () => {
    const { actions } = renderApp(<Detail />, {
      commitments: [commitment({ status: "ready_for_review" })],
      drafts: [draft()],
      selectedId: 1,
    });
    expect(screen.getByText("I will send it by Friday.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(actions.approve).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(actions.reject).toHaveBeenCalledWith(1);
  });

  it("does not offer to prepare promises owed to me", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ direction: "owed_to_me", person: "Priya" })],
      selectedId: 1,
    });
    expect(screen.getByText(/You're waiting on Priya/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Research and draft" })).not.toBeInTheDocument();
  });

  it("announces busy work while a draft is being prepared", () => {
    renderApp(<Detail />, { commitments: [commitment()], selectedId: 1, busy: { "1": true } });
    expect(screen.getByText("Researching and drafting")).toBeInTheDocument();
  });
});

describe("DraftBody", () => {
  it("renders citations as links to a numbered source list and never injects HTML", () => {
    renderApp(
      <DraftBody body={'**Bold** claim [1].\n\n- item <img src=x onerror=alert(1)> [1]\n\nSources:\n[1] https://www.acme.test/page'} />,
    );
    expect(screen.getByText("Bold").tagName).toBe("STRONG");
    const sources = screen.getByRole("list", { name: "Sources" });
    const link = within(sources).getByRole("link", { name: "acme.test" });
    expect(link).toHaveAttribute("href", "https://www.acme.test/page");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByRole("link", { name: "Source 1" })[0]).toHaveAttribute("href", "#src-1");
    expect(document.querySelector("img")).toBeNull();
  });
});
