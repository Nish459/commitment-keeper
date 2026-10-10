import { useEffect, useRef, useState } from "react";

import { dueLabel, plural } from "../format";
import { useApp } from "../state";
import type { Completion, Suggestion } from "../types";

const FILE_TYPES = ".eml,.mbox,message/rfc822,application/mbox";

const who = (s: Suggestion) =>
  s.direction === "owed_by_me" ? `You promised ${s.person}` : `${s.person} promised you`;

const owes = (c: Completion) =>
  c.direction === "owed_by_me" ? `You owed ${c.person}` : `${c.person} owed you`;

function addLabel(adds: number, kept: number, hasSuggestions: boolean): string {
  if (adds > 0 && kept > 0) return `Add ${plural(adds, "promise")} and mark ${kept} kept`;
  if (kept > 0) return `Mark ${kept} kept`;
  return hasSuggestions ? `Add ${plural(adds, "promise")} to my ledger` : "Mark 0 kept";
}

export function InboxPanel() {
  const { state, actions, today } = useApp();
  const result = state.inbox;
  const scanning = Boolean(state.busy["inbox"]);
  const adding = Boolean(state.busy["inbox-add"]);
  const files = useRef<HTMLInputElement>(null);
  const [skipped, setSkipped] = useState<ReadonlySet<number>>(new Set());
  // Closing a promise hides an obligation, so unlike new promises these start unticked.
  const [tickedDone, setTickedDone] = useState<ReadonlySet<number>>(new Set());

  useEffect(() => {
    setSkipped(new Set());
    setTickedDone(new Set());
  }, [result]);

  const picked = result ? result.suggestions.filter((_, i) => !skipped.has(i)) : [];
  const pickedDone = result
    ? result.completions.filter((c) => tickedDone.has(c.commitment_id)).map((c) => c.commitment_id)
    : [];
  const flip = (set: ReadonlySet<number>, key: number) => {
    const next = new Set(set);
    if (!next.delete(key)) next.add(key);
    return next;
  };

  const found = result ? result.suggestions.length : 0;
  const looksDone = result ? result.completions.length : 0;
  const headline = !result
    ? ""
    : found + looksDone === 0
      ? "No new promises found."
      : [
          found ? `Found ${plural(found, "promise")} in ${plural(result.emails_read, "email")}.` : "",
          looksDone
            ? `${looksDone === 1 ? "1 promise looks" : `${looksDone} promises look`} done.`
            : "",
        ]
          .filter(Boolean)
          .join(" ");

  return (
    <section className="inbox" aria-labelledby="inbox-title">
      <div className="section-head">
        <h2 id="inbox-title">Your mail</h2>
        {!result && (
          <div className="inbox-actions">
            <input
              ref={files}
              className="visually-hidden"
              type="file"
              multiple
              accept={FILE_TYPES}
              aria-label="Choose email files"
              tabIndex={-1}
              onChange={(event) => {
                const chosen = Array.from(event.target.files ?? []);
                event.target.value = "";
                if (chosen.length) void actions.scanInbox(chosen);
              }}
            />
            <button
              className="btn btn-primary"
              type="button"
              disabled={scanning}
              onClick={() => files.current?.click()}
            >
              Choose email files
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              disabled={scanning}
              onClick={() => void actions.scanInbox("sample")}
            >
              Try a sample inbox
            </button>
          </div>
        )}
      </div>

      {scanning && (
        <div className="working" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <div>
            <p className="working-title">Reading your mail</p>
            <p className="note">
              Nemotron Nano reads each email, then Nemotron Super checks for finished promises. This can take
              a few seconds.
            </p>
          </div>
        </div>
      )}

      {!scanning && !result && (
        <>
          <p className="note">
            Choose emails (<code>.eml</code> or <code>.mbox</code>, such as a Google Takeout export) and Kept
            suggests the promises in them, and notices when an email shows one was already kept. You approve
            each change before it happens.
          </p>
          <p className="note">
            Privacy: the sender&rsquo;s name, the subject and the text go to Nebius Token Factory, to
            Nemotron Nano and Super. Nothing is stored until you add it.
          </p>
        </>
      )}

      {!scanning && result && (
        <div className="inbox-result">
          <p className="week-summary">{headline}</p>
          {result.emails_skipped > 0 && (
            <p className="note">
              {plural(result.emails_skipped, "email")} not read: newsletters, automated mail, empty
              messages, or older mail beyond the limit.
            </p>
          )}

          {found > 0 && (
            <ul className="suggestions" aria-label="Promises found in your mail">
              {result.suggestions.map((s, i) => (
                <li key={`${s.source_id}-${s.source_quote}`}>
                  <label className="suggestion">
                    <input
                      type="checkbox"
                      checked={!skipped.has(i)}
                      onChange={() => setSkipped(flip(skipped, i))}
                    />
                    <span>
                      <span className="suggestion-title">
                        {who(s)}: {s.description}
                      </span>
                      <span className="suggestion-meta">
                        {dueLabel(s.due, today)} · {s.source_id}
                      </span>
                      <q className="suggestion-quote">{s.source_quote}</q>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}

          {looksDone > 0 && (
            <>
              <h3 className="inbox-subhead">Looks done</h3>
              <p className="note">Tick the ones that really are done. Nothing is closed until you do.</p>
              <ul className="suggestions" aria-label="Promises your mail shows are done">
                {result.completions.map((c) => (
                  <li key={c.commitment_id}>
                    <label className="suggestion">
                      <input
                        type="checkbox"
                        checked={tickedDone.has(c.commitment_id)}
                        onChange={() => setTickedDone(flip(tickedDone, c.commitment_id))}
                      />
                      <span>
                        <span className="suggestion-title">
                          {owes(c)}: {c.description}
                        </span>
                        <span className="suggestion-meta">Mark as kept · {c.source_id}</span>
                        <q className="suggestion-quote">{c.source_quote}</q>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}

          <div className="inbox-actions">
            {found + looksDone > 0 && (
              <button
                className="btn btn-primary"
                type="button"
                disabled={adding || picked.length + pickedDone.length === 0}
                onClick={() => void actions.acceptSuggestions(picked, pickedDone)}
              >
                {adding ? "Applying…" : addLabel(picked.length, pickedDone.length, found > 0)}
              </button>
            )}
            <button className="btn btn-secondary" type="button" disabled={adding} onClick={actions.dismissInbox}>
              {found + looksDone > 0 ? "Dismiss" : "Scan other mail"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
