import { useState, type FormEvent } from "react";

import { useApp } from "../state";

export function DemoBanner() {
  const { state, actions } = useApp();
  const { demo, access_code: hasCode, unlocked } = state.capabilities;
  const [dismissed, setDismissed] = useState(false);
  const [asking, setAsking] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  if (!demo || dismissed) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    const ok = await actions.unlockDemo(code.trim());
    setBusy(false);
    if (ok) {
      setAsking(false);
      setCode("");
    }
  }

  return (
    <aside className="demo-banner" aria-label="About this demo">
      <div className="demo-banner-text">
        <p>
          <strong>Demo workspace.</strong> Private to this browser, with sample promises. Approving a
          draft marks it kept; nothing is emailed.{unlocked && " Full access is on."}
        </p>
        {hasCode && !unlocked && !asking && (
          <button className="btn btn-quiet" type="button" onClick={() => setAsking(true)}>
            Have an access code?
          </button>
        )}
        {asking && !unlocked && (
          <form className="demo-code" onSubmit={(e) => void submit(e)}>
            <label>
              <span className="visually-hidden">Access code</span>
              <input
                type="password"
                autoComplete="off"
                required
                value={code}
                placeholder="Access code"
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "Checking…" : "Unlock"}
            </button>
            <button className="btn btn-quiet" type="button" onClick={() => setAsking(false)}>
              Cancel
            </button>
          </form>
        )}
      </div>
      <button className="demo-dismiss" type="button" aria-label="Dismiss this notice" onClick={() => setDismissed(true)}>
        ×
      </button>
    </aside>
  );
}
