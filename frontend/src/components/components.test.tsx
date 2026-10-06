import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { commitment, draft, renderApp, TODAY } from "../testing";
import { App } from "../App";
import { DemoBanner } from "./DemoBanner";
import { Detail, quoteText } from "./Detail";
import { Hero } from "./Hero";
import { Ledger } from "./Ledger";
import { ProfileDialog } from "./ProfileDialog";
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

describe("Hero sweep", () => {
  const two = [
    commitment({ id: 1, due: "2026-10-07" }),
    commitment({ id: 2, due: "2026-10-08", person: "Marcus" }),
  ];

  it("offers to draft everything due soon when there are at least two", async () => {
    const { actions } = renderApp(<Hero />, { commitments: two });
    await userEvent.click(screen.getByRole("button", { name: "Draft all 2 due soon" }));
    expect(actions.sweep).toHaveBeenCalled();
  });

  it("stays out of the way for a single promise", () => {
    renderApp(<Hero />, { commitments: [two[0]!] });
    expect(screen.queryByRole("button", { name: /Draft all/ })).not.toBeInTheDocument();
  });

  it("ignores far-off, rejected and promises owed to me", () => {
    renderApp(<Hero />, {
      commitments: [
        commitment({ id: 1, due: "2026-10-07" }),
        commitment({ id: 2, due: "2026-10-30" }),
        commitment({ id: 3, due: "2026-10-07", direction: "owed_to_me" }),
        commitment({ id: 4, due: "2026-10-07" }),
      ],
      drafts: [draft({ id: 9, commitment_id: 4, status: "rejected" })],
    });
    expect(screen.queryByRole("button", { name: /Draft all/ })).not.toBeInTheDocument();
  });

  it("shows progress while sweeping", () => {
    renderApp(<Hero />, { commitments: two, busy: { sweep: true } });
    expect(screen.getByRole("button", { name: "Drafting…" })).toBeDisabled();
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

describe("Detail calendar link", () => {
  it("offers a calendar download for a promise with a due date", () => {
    renderApp(<Detail />, { commitments: [commitment({ id: 7 })], selectedId: 7 });
    const link = screen.getByRole("link", { name: "Add to calendar" });
    expect(link).toHaveAttribute("href", "/api/commitments/7/calendar.ics");
    expect(link).toHaveAttribute("download");
  });

  it("offers nothing when there is no due date", () => {
    renderApp(<Detail />, { commitments: [commitment({ due: null })], selectedId: 1 });
    expect(screen.queryByRole("link", { name: "Add to calendar" })).not.toBeInTheDocument();
  });
});

describe("Detail draft editing", () => {
  const pending = {
    commitments: [commitment({ status: "ready_for_review" })],
    drafts: [draft()],
    selectedId: 1,
  };

  it("edits subject and message and saves them", async () => {
    const { actions } = renderApp(<Detail />, pending);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    const subject = screen.getByLabelText("Subject");
    const message = screen.getByLabelText("Message");
    expect(subject).toHaveValue("Comparison");
    expect(message).toHaveValue(draft().body);

    await userEvent.clear(subject);
    await userEvent.type(subject, "Updated subject");
    await userEvent.clear(message);
    await userEvent.type(message, "Updated message");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(actions.saveDraft).toHaveBeenCalledWith(1, "Updated subject", "Updated message");
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("cancels without saving", async () => {
    const { actions } = renderApp(<Detail />, pending);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.type(screen.getByLabelText("Subject"), " changed");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(actions.saveDraft).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Comparison" })).toBeInTheDocument();
  });

  it("does not offer editing for a draft that was already approved", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ status: "done" })],
      drafts: [draft({ status: "approved" })],
      selectedId: 1,
    });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });
});

describe("Detail email sending", () => {
  const pending = {
    commitments: [commitment({ status: "ready_for_review" })],
    drafts: [draft()],
    selectedId: 1,
  };
  const emailOn = (recipients: string[]) => ({
    capabilities: { email: { enabled: true, sender: "me@example.com", recipients }, demo: false },
  });

  it("offers a plain Approve when email is not configured", () => {
    renderApp(<Detail />, pending);
    expect(screen.queryByLabelText(/Send to/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send email" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByText(/Sending is off/)).toBeInTheDocument();
  });

  it("prefills the recipient from a remembered contact and sends on submit", async () => {
    const { actions } = renderApp(<Detail />, {
      ...pending,
      ...emailOn(["priya@acme.com", "@corp.com"]),
      contacts: { priya: "priya@acme.com" },
    });
    expect(screen.getByLabelText(/Send to/)).toHaveValue("priya@acme.com");
    expect(screen.getByText(/Sending as me@example.com. Kept can only email priya@acme.com, @corp.com/)).toBeInTheDocument();
    expect(screen.queryByText(/Sending is off/)).not.toBeInTheDocument();

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


describe("App header profile", () => {
  it("asks for a name when none is set", () => {
    renderApp(<App />);
    expect(screen.getByRole("button", { name: "Add your name" })).toBeInTheDocument();
  });

  it("opens the name dialog from the header", async () => {
    const { actions } = renderApp(<App />, { profileName: "Ada Lovelace" });
    await userEvent.click(screen.getByRole("button", { name: "Signing as Ada Lovelace" }));
    expect(actions.openProfile).toHaveBeenCalled();
  });
});

describe("ProfileDialog", () => {
  it("saves the trimmed name", async () => {
    const { actions } = renderApp(<ProfileDialog />, { profileName: "", profileOpen: true });
    const input = screen.getByLabelText("Name", { selector: "input" });
    await userEvent.type(input, "  Ada Lovelace ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(actions.saveProfile).toHaveBeenCalledWith("Ada Lovelace");
  });
});


describe("Demo mode", () => {
  const demo = { capabilities: { email: { enabled: false, sender: "", recipients: [] }, demo: true } };

  it("tells visitors the workspace is private and temporary", () => {
    renderApp(<DemoBanner />, demo);
    expect(screen.getByText(/This is a demo workspace/)).toBeInTheDocument();
    expect(screen.getByText(/Email sending is off/)).toBeInTheDocument();
  });

  it("shows nothing outside the demo", () => {
    renderApp(<DemoBanner />);
    expect(screen.queryByText(/demo workspace/)).not.toBeInTheDocument();
  });

  it("explains that sending is disabled in the demo instead of pointing at .env", () => {
    renderApp(<Detail />, {
      ...demo,
      commitments: [commitment({ status: "ready_for_review" })],
      drafts: [draft()],
      selectedId: 1,
    });
    expect(screen.getByText(/Sending is turned off in the demo/)).toBeInTheDocument();
    expect(screen.queryByText(/SMTP/)).not.toBeInTheDocument();
  });
});
