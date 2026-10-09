import { useEffect, useRef, useState } from "react";

import { dueLabel, plural } from "../format";
import { useApp } from "../state";
import type { Suggestion } from "../types";

const FILE_TYPES = ".eml,.mbox,message/rfc822,application/mbox";

const who = (s: Suggestion) =>
  s.direction === "owed_by_me" ? `You promised ${s.person}` : `${s.person} promised you`;

export function InboxPanel() {
  const { state, actions, today } = useApp();
  const result = state.inbox;
  const scanning = Boolean(state.busy["inbox"]);
  const adding = Boolean(state.busy["inbox-add"]);
  const files = useRef<HTMLInputElement>(null);
  const [skipped, setSkipped] = useState<ReadonlySet<number>>(new Set());

  useEffect(() => setSkipped(new Set()), [result]);

  const picked = result ? result.suggestions.filter((_, i) => !skipped.has(i)) : [];
  const toggle = (index: number) =>
    setSkipped((current) => {
      const next = new Set(current);
      if (!next.delete(index)) next.add(index);
      return next;
    });

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
            <p className="note">Nemotron is looking for promises in each email. This can take a few seconds.</p>
          </div>
        </div>
      )}

      {!scanning && !result && (
        <>
          <p className="note">
            Choose emails (<code>.eml</code> or <code>.mbox</code>, such as a Google Takeout export) and Kept
            suggests the promises in them. You approve each one before it is added.
          </p>
          <p className="note">
            Privacy: the sender&rsquo;s name, the subject and the text go to Nebius Token Factory. Nothing is
            stored until you add it.
          </p>
        </>
      )}

      {!scanning && result && (
        <div className="inbox-result">
          <p className="week-summary">
            {result.suggestions.length === 0
              ? "No new promises found."
              : `Found ${plural(result.suggestions.length, "promise")} in ${plural(result.emails_read, "email")}.`}
          </p>
          {result.emails_skipped > 0 && (
            <p className="note">
              {plural(result.emails_skipped, "email")} not read: newsletters, automated mail, empty
              messages, or older mail beyond the limit.
            </p>
          )}

          {result.suggestions.length > 0 && (
            <ul className="suggestions" aria-label="Promises found in your mail">
              {result.suggestions.map((s, i) => (
                <li key={`${s.source_id}-${s.source_quote}`}>
                  <label className="suggestion">
                    <input type="checkbox" checked={!skipped.has(i)} onChange={() => toggle(i)} />
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

          <div className="inbox-actions">
            {result.suggestions.length > 0 && (
              <button
                className="btn btn-primary"
                type="button"
                disabled={adding || picked.length === 0}
                onClick={() => void actions.acceptSuggestions(picked)}
              >
                {adding ? "Adding…" : `Add ${plural(picked.length, "promise")} to my ledger`}
              </button>
            )}
            <button className="btn btn-secondary" type="button" disabled={adding} onClick={actions.dismissInbox}>
              {result.suggestions.length > 0 ? "Dismiss" : "Scan other mail"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
