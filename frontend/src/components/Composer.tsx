import { useEffect, useRef, useState, type FormEvent } from "react";

import { useApp, type ComposerMode } from "../state";
import type { Direction } from "../types";

const SAMPLE = [
  "Standup with Priya (Acme Corp).",
  "I will send her a competitor comparison of Tavily vs Exa vs Perplexity API for search by Friday.",
  "Priya said she will share the Q3 pricing deck by Wednesday.",
  "I also promised Marcus I'd review his onboarding doc by next Monday.",
].join(" ");

const stamp = () => new Date().toISOString().slice(0, 16).replace("T", " ");

const TABS: { id: ComposerMode; label: string }[] = [
  { id: "notes", label: "Paste notes" },
  { id: "hand", label: "Add one by hand" },
];

export function Composer() {
  const { state, actions } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const [mode, setMode] = useState<ComposerMode>("notes");
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [direction, setDirection] = useState<Direction>("owed_by_me");
  const [person, setPerson] = useState("");
  const [what, setWhat] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { open, sample, mode: requestedMode } = state.composer;

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) {
      setError("");
      setMode(requestedMode);
      if (sample) {
        setName((current) => current || `Sample standup ${stamp()}`);
        setText(SAMPLE);
      }
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open, sample, requestedMode]);

  async function run(work: () => Promise<void>, reset: () => void) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await work();
      reset();
      actions.closeComposer();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const submitNotes = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => actions.ingest(name.trim(), text.trim()),
      () => {
        setName("");
        setText("");
      },
    );
  };

  const submitPromise = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => actions.addPromise({ direction, person: person.trim(), description: what.trim(), due: due || null }),
      () => {
        setPerson("");
        setWhat("");
        setDue("");
      },
    );
  };

  const switchTo = (next: ComposerMode) => {
    setMode(next);
    setError("");
  };

  return (
    <dialog ref={dialog} className="composer" aria-labelledby="composer-title" onClose={actions.closeComposer}>
      <div className="composer-form">
        <h2 id="composer-title">Add promises</h2>

        <div className="tabs" role="tablist" aria-label="How to add">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              id={`tab-${tab.id}`}
              role="tab"
              type="button"
              className="tab"
              aria-selected={mode === tab.id}
              aria-controls={`panel-${tab.id}`}
              disabled={busy}
              onClick={() => switchTo(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {mode === "notes" ? (
          <form
            id="panel-notes"
            role="tabpanel"
            aria-labelledby="tab-notes"
            className="composer-panel"
            onSubmit={submitNotes}
          >
            <p className="note">
              Paste meeting notes, a transcript or an email. Kept finds the promises in it. The text goes only
              to Nebius Token Factory.
            </p>
            <label className="field">
              <span>Name this note</span>
              <input
                required
                maxLength={200}
                value={name}
                placeholder="Standup, 6 Oct"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Notes</span>
              <textarea
                required
                rows={9}
                maxLength={50000}
                value={text}
                placeholder="Paste text here"
                onChange={(e) => setText(e.target.value)}
              />
            </label>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="composer-actions">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {busy ? "Finding promises…" : "Find promises"}
              </button>
              <button className="btn btn-secondary" type="button" disabled={busy} onClick={actions.closeComposer}>
                Cancel
              </button>
              <button
                className="btn btn-quiet"
                type="button"
                disabled={busy}
                onClick={() => {
                  setName((current) => current || `Sample standup ${stamp()}`);
                  setText(SAMPLE);
                }}
              >
                Use a sample note
              </button>
            </div>
          </form>
        ) : (
          <form
            id="panel-hand"
            role="tabpanel"
            aria-labelledby="tab-hand"
            className="composer-panel"
            onSubmit={submitPromise}
          >
            <p className="note">Type it in directly. It&rsquo;s saved instantly, with no model involved.</p>
            <fieldset className="choice">
              <legend>Who made the promise?</legend>
              <label>
                <input
                  type="radio"
                  name="direction"
                  checked={direction === "owed_by_me"}
                  onChange={() => setDirection("owed_by_me")}
                />
                I did
              </label>
              <label>
                <input
                  type="radio"
                  name="direction"
                  checked={direction === "owed_to_me"}
                  onChange={() => setDirection("owed_to_me")}
                />
                They did
              </label>
            </fieldset>
            <label className="field">
              <span>{direction === "owed_by_me" ? "Who is it for?" : "Who promised you?"}</span>
              <input
                required
                maxLength={100}
                value={person}
                placeholder="Priya"
                onChange={(e) => setPerson(e.target.value)}
              />
            </label>
            <label className="field">
              <span>What was promised?</span>
              <input
                required
                maxLength={300}
                value={what}
                placeholder="Send the Q3 pricing deck"
                onChange={(e) => setWhat(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Due date (optional)</span>
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="composer-actions">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {busy ? "Adding…" : "Add promise"}
              </button>
              <button className="btn btn-secondary" type="button" disabled={busy} onClick={actions.closeComposer}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
