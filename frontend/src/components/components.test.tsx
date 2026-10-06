import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { commitment, draft, renderApp, TODAY } from "../testing";
import { Detail, quoteText } from "./Detail";
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
    expect(screen.getByRole("heading")).toHaveTextContent("Next up for Priya: Send the comparison. Due Fri.");
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

describe("Detail email sending", () => {
  const pending = {
    commitments: [commitment({ status: "ready_for_review" })],
    drafts: [draft()],
    selectedId: 1,
  };
  const emailOn = (recipients: string[]) => ({
    capabilities: { email: { enabled: true, sender: "me@example.com", recipients } },
  });

  it("offers a plain Approve when email is not configured", () => {
    renderApp(<Detail />, pending);
    expect(screen.queryByLabelText(/Send to/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send email" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("prefills the recipient from a remembered contact and sends on submit", async () => {
    const { actions } = renderApp(<Detail />, {
      ...pending,
      ...emailOn(["priya@acme.com", "@corp.com"]),
      contacts: { priya: "priya@acme.com" },
    });
    expect(screen.getByLabelText(/Send to/)).toHaveValue("priya@acme.com");
    expect(screen.getByText(/Kept can only email priya@acme.com, @corp.com/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Send email" }));
    expect(actions.approve).toHaveBeenCalledWith(1, "priya@acme.com");
  });

  it("prefills the only allowed recipient and still allows approving without sending", async () => {
    const { actions } = renderApp(<Detail />, { ...pending, ...emailOn(["me@example.com"]) });
    expect(screen.getByLabelText(/Send to/)).toHaveValue("me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Approve without sending" }));
    expect(actions.approve).toHaveBeenCalledWith(1);
  });

  it("does not send without a recipient", async () => {
    const { actions } = renderApp(<Detail />, { ...pending, ...emailOn(["a@x.com", "b@x.com"]) });
    expect(screen.getByLabelText(/Send to/)).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Send email" }));
    expect(actions.approve).not.toHaveBeenCalled();
  });

  it("shows who a sent draft went to", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ status: "done" })],
      drafts: [draft({ status: "approved", sent_to: "priya@acme.com", sent_at: "2026-10-06T12:00:00Z" })],
      selectedId: 1,
    });
    expect(screen.getByText(/Sent to priya@acme.com on/)).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
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


describe("quoteText", () => {
  it("marks mid-sentence excerpts with an ellipsis and leaves full sentences alone", () => {
    expect(quoteText("she will share the deck by Wednesday.")).toBe("…she will share the deck by Wednesday.");
    expect(quoteText("I will send it by Friday.")).toBe("I will send it by Friday.");
  });
});
