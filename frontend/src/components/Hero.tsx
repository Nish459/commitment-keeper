import { dueLabel, plural } from "../format";
import { byDue, isClosed, isOverdue, latestDraft, shorten } from "../selectors";
import { useApp } from "../state";

export function Hero() {
  const { state, actions, today } = useApp();
  const { commitments, drafts, loading, busy } = state;

  if (loading) {
    return (
      <section className="hero" aria-labelledby="headline">
        <h1 id="headline">Loading your promises.</h1>
      </section>
    );
  }

  if (commitments.length === 0) {
    return (
      <section className="hero" aria-labelledby="headline">
        <h1 id="headline">Nothing to keep yet.</h1>
        <p className="hero-sub">
          Add meeting notes and Kept finds the promises in them, then does the groundwork before they're
          due.
        </p>
        <div className="hero-actions">
          <button className="btn btn-primary" type="button" onClick={() => actions.openComposer()}>
            Add notes
          </button>
          <button className="btn btn-quiet" type="button" onClick={() => actions.openComposer({ sample: true })}>
            Try a sample note
          </button>
        </div>
      </section>
    );
  }

  const open = commitments.filter((c) => !isClosed(c));
  const owedByMe = open.filter((c) => c.direction === "owed_by_me");
  const owedToMe = open.filter((c) => c.direction === "owed_to_me");
  const ready = commitments.filter((c) => c.status === "ready_for_review");
  const overdue = open.filter((c) => isOverdue(c, today));
  const kept = commitments.filter((c) => c.status === "done").length;
  const next = [...owedByMe].sort(byDue).find((c) => c.status === "open");

  let headline: string;
  let action: React.ReactNode = null;
  const [firstReady] = ready;
  if (firstReady) {
    headline = `${plural(ready.length, "draft")} ready for your approval.`;
    action = (
      <button
        className="btn btn-primary"
        type="button"
        onClick={() => actions.select(firstReady.id, { scroll: true })}
      >
        {ready.length === 1 ? "Review the draft" : "Review the first draft"}
      </button>
    );
  } else if (overdue.length) {
    headline = `${plural(overdue.length, "promise")} overdue.`;
  } else if (next) {
    headline = `Next up: ${shorten(next.description, 72)}, ${dueLabel(next.due, today).toLowerCase()}.`;
  } else {
    headline = "Nothing is due soon.";
  }

  if (!action && next && !latestDraft(drafts, next.id) && !busy[String(next.id)]) {
    action = (
      <button className="btn btn-primary" type="button" onClick={() => void actions.prepare(next.id)}>
        Research and draft
      </button>
    );
  }

  return (
    <section className="hero" aria-labelledby="headline">
      <h1 id="headline">{headline}</h1>
      <p className="hero-sub">
        You owe {owedByMe.length} and are owed {owedToMe.length}. {kept} kept so far.
      </p>
      {action && <div className="hero-actions">{action}</div>}
    </section>
  );
}
