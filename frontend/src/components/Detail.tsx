import { useState } from "react";

import { dueLabel } from "../format";
import { isOverdue, latestDraft } from "../selectors";
import { useApp } from "../state";
import type { Commitment, Draft } from "../types";
import { DraftBody } from "./RichText";
import { Seal, SEAL_LABEL } from "./Seal";

function DraftView({ draft, person }: { draft: Draft; person: string }) {
  const { state, actions } = useApp();
  const { email } = state.capabilities;
  const pending = draft.status === "pending";
  const working = Boolean(state.busy[`draft-${draft.id}`]);
  const remembered = state.contacts[person.toLowerCase()];
  const [to, setTo] = useState(remembered ?? (email.recipients.length === 1 ? email.recipients[0] : "") ?? "");
  const sentOn = draft.sent_at ? new Date(draft.sent_at).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }) : "";

  return (
    <article className="draft" aria-label="Email draft">
      <div className="draft-head">
        <h3 className="draft-subject">{draft.subject}</h3>
        {!pending && (
          <span className={`draft-state is-${draft.status}`}>
            {draft.status === "approved" ? (draft.sent_to ? "Sent" : "Approved") : "Rejected"}
          </span>
        )}
      </div>
      {draft.sent_to && (
        <p className="note">
          Sent to {draft.sent_to} on {sentOn}.
        </p>
      )}
      <DraftBody body={draft.body} />
      <form
        className="draft-actions"
        onSubmit={(event) => {
          event.preventDefault();
          void actions.approve(draft.id, to.trim());
        }}
      >
        {pending && email.enabled && (
          <label className="send-to">
            <span>Send to</span>
            <input
              type="email"
              required
              value={to}
              placeholder="name@example.com"
              onChange={(e) => setTo(e.target.value)}
              aria-describedby={`allowed-${draft.id}`}
            />
            <span className="note" id={`allowed-${draft.id}`}>
              Kept can only email {email.recipients.join(", ")}.
            </span>
          </label>
        )}
        <div className="draft-buttons">
          {pending && email.enabled && (
            <button className="btn btn-primary" type="submit" disabled={working}>
              {working ? "Sending…" : "Send email"}
            </button>
          )}
          {pending && (
            <button
              className={`btn ${email.enabled ? "btn-secondary" : "btn-primary"}`}
              type="button"
              disabled={working}
              onClick={() => void actions.approve(draft.id)}
            >
              {email.enabled ? "Approve without sending" : "Approve"}
            </button>
          )}
          {pending && (
            <button
              className="btn btn-secondary"
              type="button"
              disabled={working}
              onClick={() => void actions.reject(draft.id)}
            >
              Reject
            </button>
          )}
          <button className="btn btn-quiet" type="button" onClick={() => void actions.copy(draft)}>
            Copy email
          </button>
        </div>
      </form>
    </article>
  );
}

function WorkArea({ c, draft }: { c: Commitment; draft: Draft | null }) {
  const { state, actions } = useApp();

  if (c.direction === "owed_to_me") {
    return <p className="note">You're waiting on {c.person}. There's nothing for Kept to prepare.</p>;
  }
  if (state.busy[String(c.id)]) {
    return (
      <div className="working" aria-busy="true">
        <span className="spinner" aria-hidden="true" />
        <div>
          <p className="working-title">Researching and drafting</p>
          <p className="note">Searching the web and writing the email. This usually takes about 10 seconds.</p>
        </div>
      </div>
    );
  }
  if (draft && (draft.status === "pending" || draft.status === "approved")) {
    return <DraftView key={draft.id} draft={draft} person={c.person} />;
  }
  if (c.status === "done") return <p className="note">Marked as kept.</p>;

  const again = draft?.status === "rejected";
  return (
    <div className="prepare">
      <p className="note">
        {again
          ? "You rejected the last draft. Kept can research this again and write a new one."
          : "Kept can research this on the web and write the email for you to review. Nothing is sent."}
      </p>
      <button className="btn btn-primary" type="button" onClick={() => void actions.prepare(c.id)}>
        {again ? "Draft again" : "Research and draft"}
      </button>
    </div>
  );
}

export function Detail() {
  const { state, today } = useApp();
  const c = state.commitments.find((x) => x.id === state.selectedId);

  return (
    <aside className="detail" id="detail" aria-label="Selected promise">
      {!c ? (
        <div className="detail-card detail-empty">
          <p className="detail-empty-title">Pick a promise</p>
          <p className="note">
            Select one from the due dates or the ledger to see where it came from and what Kept has
            prepared.
          </p>
        </div>
      ) : (
        <div className="detail-card">
          <header className="detail-head">
            <p className="detail-who">
              {c.direction === "owed_by_me" ? `You promised ${c.person}` : `${c.person} promised you`}
            </p>
            <h2 className="detail-title">{c.description}</h2>
            <p className="detail-meta">
              <span className={`detail-status seal-tone-${c.status}`}>
                <Seal status={c.status} />
                {SEAL_LABEL[c.status]}
              </span>
              <span className={isOverdue(c, today) ? "is-overdue" : undefined}>{dueLabel(c.due, today)}</span>
            </p>
          </header>
          <figure className="provenance">
            <blockquote>{c.source_quote}</blockquote>
            <figcaption>From {c.source_id}</figcaption>
          </figure>
          <WorkArea c={c} draft={latestDraft(state.drafts, c.id)} />
        </div>
      )}
    </aside>
  );
}
