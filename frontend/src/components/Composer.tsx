import { useEffect, useRef, useState, type FormEvent } from "react";

import { useApp } from "../state";

const SAMPLE = [
  "Standup with Priya (Acme Corp).",
  "I will send her a competitor comparison of Tavily vs Exa vs Perplexity API for search by Friday.",
  "Priya said she will share the Q3 pricing deck by Wednesday.",
  "I also promised Marcus I'd review his onboarding doc by next Monday.",
].join(" ");

const stamp = () => new Date().toISOString().slice(0, 16).replace("T", " ");

export function Composer() {
  const { state, actions } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { open, sample } = state.composer;

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) {
      setError("");
      if (sample) {
        setName((current) => current || `Sample standup ${stamp()}`);
        setText(SAMPLE);
      }
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open, sample]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await actions.ingest(name.trim(), text.trim());
      setName("");
      setText("");
      actions.closeComposer();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="composer"
      aria-labelledby="composer-title"
      onClose={actions.closeComposer}
    >
      <form className="composer-form" onSubmit={(e) => void submit(e)}>
        <h2 id="composer-title">Add notes</h2>
        <p className="note">
          Paste meeting notes, a transcript or an email. Kept finds the promises in it. The text goes only to
          Nebius Token Factory.
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
    </dialog>
  );
}
