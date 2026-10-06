import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { commitment, draft, renderApp, TODAY } from "../testing";
import { App } from "../App";
import { DemoBanner } from "./DemoBanner";
import { Composer } from "./Composer";
import { Detail, quoteText } from "./Detail";
import { Hero } from "./Hero";
import { WeekCheckPanel } from "./WeekCheckPanel";
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
    capabilities: { email: { enabled: true, sender: "me@example.com", recipients }, demo: false, access_code: false, unlocked: false },
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

  it("opens the add dialog from the header button", async () => {
    const { actions } = renderApp(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Add promises" }));
    expect(actions.openComposer).toHaveBeenCalledWith();
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
  const caps = (extra: { access_code?: boolean; unlocked?: boolean } = {}) => ({
    capabilities: {
      email: { enabled: false, sender: "", recipients: [] },
      demo: true,
      access_code: false,
      unlocked: false,
      ...extra,
    },
  });

  it("tells visitors the workspace is private and that nothing is emailed", () => {
    renderApp(<DemoBanner />, caps());
    expect(screen.getByText("Demo workspace.")).toBeInTheDocument();
    expect(screen.getByText(/nothing is emailed/)).toBeInTheDocument();
  });

  it("shows nothing outside the demo", () => {
    renderApp(<DemoBanner />);
    expect(screen.queryByText(/Demo workspace/)).not.toBeInTheDocument();
  });

  it("can be dismissed", async () => {
    renderApp(<DemoBanner />, caps());
    await userEvent.click(screen.getByRole("button", { name: "Dismiss this notice" }));
    expect(screen.queryByText(/Demo workspace/)).not.toBeInTheDocument();
  });

  it("does not mention an access code when there is none", () => {
    renderApp(<DemoBanner />, caps());
    expect(screen.queryByRole("button", { name: "Have an access code?" })).not.toBeInTheDocument();
  });

  it("lets a judge enter the access code", async () => {
    const { actions } = renderApp(<DemoBanner />, caps({ access_code: true }));
    await userEvent.click(screen.getByRole("button", { name: "Have an access code?" }));
    await userEvent.type(screen.getByLabelText("Access code"), "  judge-2026 ");
    await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(actions.unlockDemo).toHaveBeenCalledWith("judge-2026");
  });

  it("confirms once full access is on and stops asking", () => {
    renderApp(<DemoBanner />, caps({ access_code: true, unlocked: true }));
    expect(screen.getByText(/Full access is on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Have an access code?" })).not.toBeInTheDocument();
  });

  it("explains approving in the demo instead of pointing at .env", () => {
    renderApp(<Detail />, {
      ...caps(),
      commitments: [commitment({ status: "ready_for_review" })],
      drafts: [draft()],
      selectedId: 1,
    });
    expect(screen.getByText(/In the demo, approving marks the promise as kept/)).toBeInTheDocument();
    expect(screen.queryByText(/SMTP/)).not.toBeInTheDocument();
  });
});

describe("WeekCheckPanel", () => {
  const two = [
    commitment({ id: 1, description: "Send the comparison" }),
    commitment({ id: 2, person: "Marcus", description: "Review the doc", due: "2026-10-12" }),
  ];
  const result = {
    summary: "A busy Friday.",
    concerns: [
      {
        commitment_ids: [1, 2, 404],
        title: "Friday crunch",
        explanation: "Two things land together.",
        severity: "high" as const,
      },
    ],
    suggested_order: [
      { commitment_id: 2, reason: "Quick win first" },
      { commitment_id: 1, reason: "Then the big one" },
    ],
    model_used: "Nemotron 3 Ultra",
  };

  it("stays hidden until there are at least two open promises", () => {
    renderApp(<WeekCheckPanel />, { commitments: [two[0]!] });
    expect(screen.queryByRole("heading", { name: "Week check" })).not.toBeInTheDocument();
  });

  it("invites a check and asks Ultra when clicked", async () => {
    const { actions } = renderApp(<WeekCheckPanel />, { commitments: two });
    await userEvent.click(screen.getByRole("button", { name: "Check my week" }));
    expect(actions.checkWeek).toHaveBeenCalled();
  });

  it("shows progress while Ultra works", () => {
    renderApp(<WeekCheckPanel />, { commitments: two, busy: { week: true } });
    expect(screen.getByText(/Nemotron Ultra is reading/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reading your week…" })).toBeDisabled();
  });

  it("renders concerns, an ordered plan and credit, and links back to real promises only", async () => {
    const { actions } = renderApp(<WeekCheckPanel />, { commitments: two, weekCheck: result });
    expect(screen.getByText("A busy Friday.")).toBeInTheDocument();
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("Friday crunch")).toBeInTheDocument();
    expect(screen.getByText(/Reasoned by Nemotron 3 Ultra/)).toBeInTheDocument();

    const steps = within(screen.getByRole("list", { name: "Suggested order" })).getAllByRole("listitem");
    expect(steps.map((step) => step.textContent)).toEqual([
      "Marcus: Review the docQuick win first",
      "Priya: Send the comparisonThen the big one",
    ]);

    await userEvent.click(within(steps[0]!).getByRole("button", { name: /Marcus: Review the doc/ }));
    expect(actions.select).toHaveBeenCalledWith(2, { scroll: true });
    expect(screen.queryByText(/404/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("says plainly when nothing is wrong", () => {
    renderApp(<WeekCheckPanel />, {
      commitments: two,
      weekCheck: { ...result, concerns: [], suggested_order: [] },
    });
    expect(screen.getByRole("heading", { name: "Nothing to worry about" })).toBeInTheDocument();
  });
});


describe("Composer: adding a promise by hand", () => {
  const open = { composer: { open: true, sample: false, mode: "hand" as const } };

  it("opens on the by-hand tab when asked and saves exactly what was typed", async () => {
    const { actions } = renderApp(<Composer />, open);
    expect(screen.getByRole("tab", { name: "Add one by hand" })).toHaveAttribute("aria-selected", "true");

    await userEvent.type(screen.getByLabelText("Who is it for?"), "  priya ");
    await userEvent.type(screen.getByLabelText("What was promised?"), "send the deck");
    await userEvent.type(screen.getByLabelText("Due date (optional)"), "2026-10-09");
    await userEvent.click(screen.getByRole("button", { name: "Add promise" }));

    expect(actions.addPromise).toHaveBeenCalledWith({
      direction: "owed_by_me",
      person: "priya",
      description: "send the deck",
      due: "2026-10-09",
    });
    expect(actions.closeComposer).toHaveBeenCalled();
  });

  it("treats a blank due date as no deadline and can record what someone promised me", async () => {
    const { actions } = renderApp(<Composer />, open);
    await userEvent.click(screen.getByRole("radio", { name: "They did" }));
    expect(screen.getByLabelText("Who promised you?")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Who promised you?"), "Marcus");
    await userEvent.type(screen.getByLabelText("What was promised?"), "send the budget");
    await userEvent.click(screen.getByRole("button", { name: "Add promise" }));

    expect(actions.addPromise).toHaveBeenCalledWith({
      direction: "owed_to_me",
      person: "Marcus",
      description: "send the budget",
      due: null,
    });
  });

  it("shows the server's reason inline and keeps the dialog open when adding fails", async () => {
    const { actions } = renderApp(<Composer />, open);
    vi.mocked(actions.addPromise).mockRejectedValueOnce(new Error("The demo's allowance is used up."));
    await userEvent.type(screen.getByLabelText("Who is it for?"), "Priya");
    await userEvent.type(screen.getByLabelText("What was promised?"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Add promise" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The demo's allowance is used up.");
    expect(actions.closeComposer).not.toHaveBeenCalled();
  });

  it("makes only the selected tab reachable by Tab and moves between tabs with the arrow keys", async () => {
    renderApp(<Composer />, { composer: { open: true, sample: false, mode: "notes" } });
    const notes = screen.getByRole("tab", { name: "Paste notes" });
    const hand = screen.getByRole("tab", { name: "Add one by hand" });
    expect([notes.tabIndex, hand.tabIndex]).toEqual([0, -1]);

    notes.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(hand).toHaveAttribute("aria-selected", "true");
    expect(hand).toHaveFocus();
    expect([notes.tabIndex, hand.tabIndex]).toEqual([-1, 0]);

    await userEvent.keyboard("{ArrowLeft}");
    expect(notes).toHaveAttribute("aria-selected", "true");
  });

  it("switches between pasting notes and adding by hand", async () => {
    renderApp(<Composer />, { composer: { open: true, sample: false, mode: "notes" } });
    expect(screen.getByRole("button", { name: "Find promises" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Add one by hand" }));
    expect(screen.getByRole("button", { name: "Add promise" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find promises" })).not.toBeInTheDocument();
  });
});

describe("Detail for a promise added by hand", () => {
  it("says it was added by hand instead of showing an empty quote", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ source_id: "Added by hand", source_quote: "" })],
      selectedId: 1,
    });
    expect(screen.getByText("Added by hand")).toBeInTheDocument();
    expect(document.querySelector("blockquote")).toBeNull();
  });
});


describe("Attachments", () => {
  const emailOn = {
    capabilities: {
      email: { enabled: true, sender: "me@example.com", recipients: ["zoe@acme.com"] },
      demo: false,
      access_code: false,
      unlocked: false,
    },
  };
  const needsFile = {
    commitments: [commitment({ status: "ready_for_review" })],
    drafts: [draft({ needs_attachment: true })],
    selectedId: 1,
  };
  const file = { id: 5, draft_id: 1, filename: "roadmap.pdf", content_type: "application/pdf", size: 2048 };

  it("loads the draft's files and warns when the email says attached but nothing is", async () => {
    const { actions } = renderApp(<Detail />, { ...needsFile, ...emailOn });
    expect(actions.loadAttachments).toHaveBeenCalledWith(1);
    expect(screen.getByText(/This email says a file is attached. Add it before sending/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send email" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve without sending" })).toBeEnabled();
  });

  it("lists attached files and unlocks sending", async () => {
    const { actions } = renderApp(<Detail />, { ...needsFile, ...emailOn, attachments: { 1: [file] } });
    expect(screen.getByText("roadmap.pdf")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.queryByText(/Add it before sending/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add more files" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send email" })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "Remove roadmap.pdf" }));
    expect(actions.removeAttachment).toHaveBeenCalledWith(1, 5);
  });

  it("uploads every chosen file, so several can go in one email", async () => {
    const { actions } = renderApp(<Detail />, { ...needsFile, ...emailOn });
    const a = new File(["a"], "a.pdf", { type: "application/pdf" });
    const b = new File(["b"], "b.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Choose files to attach"), [a, b]);
    expect(actions.addAttachments).toHaveBeenCalledWith(1, [a, b]);
  });

  it("does not block sending an ordinary email that needs no file", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ status: "ready_for_review" })],
      drafts: [draft()],
      selectedId: 1,
      ...emailOn,
    });
    expect(screen.getByRole("button", { name: "Send email" })).toBeEnabled();
    expect(screen.queryByText(/says a file is attached/)).not.toBeInTheDocument();
  });

  it("shows a sent email's files read-only", () => {
    renderApp(<Detail />, {
      commitments: [commitment({ status: "done" })],
      drafts: [draft({ status: "approved", needs_attachment: true, sent_to: "zoe@acme.com", sent_at: "2026-10-06T12:00:00Z" })],
      selectedId: 1,
      attachments: { 1: [file] },
      ...emailOn,
    });
    expect(screen.getByRole("heading", { name: "Sent with" })).toBeInTheDocument();
    expect(screen.getByText("roadmap.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add/ })).not.toBeInTheDocument();
  });

  it("explains what to do when sending is off", () => {
    renderApp(<Detail />, needsFile);
    expect(screen.getByText(/Sending is off, so copy the text and attach the file/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose files to attach")).not.toBeInTheDocument();
  });
});
