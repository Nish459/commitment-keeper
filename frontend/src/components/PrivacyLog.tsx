import { useEffect, useRef } from "react";

import { clockTime, formatBytes, plural } from "../format";
import { useApp } from "../state";
import { ShieldIcon } from "./Seal";

const MAX_ROWS = 60;

export function PrivacyLogButton() {
  const { state, actions } = useApp();
  const sent = state.audit.length;
  return (
    <button
      className="btn btn-quiet privacy-button"
      type="button"
      aria-haspopup="dialog"
      aria-label={sent ? `Privacy log, ${plural(sent, "request")} sent out` : "Privacy log"}
      onClick={actions.togglePrivacy}
    >
      <ShieldIcon />
      <span className="privacy-label">Privacy log</span>
      {sent > 0 && <span className="privacy-count">{sent}</span>}
    </button>
  );
}

export function PrivacyLog() {
  const { state, actions } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const events = state.audit;
  const blocked = events.filter((e) => e.blocked).length;
  const open = state.privacyOpen;

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="privacy"
      aria-labelledby="privacy-title"
      onClose={actions.closePrivacy}
      onClick={(event) => event.target === dialog.current && actions.closePrivacy()}
    >
      <div className="privacy-inner">
        <div className="privacy-head">
          <h2 id="privacy-title">Everything Kept sent out</h2>
          <button className="btn btn-quiet" type="button" onClick={actions.closePrivacy}>
            Close
          </button>
        </div>
        <p className="note">
          Kept records the host, path and size of every request. Never the content.
          {events.length > 0 && ` ${plural(events.length - blocked, "request")} sent, ${blocked} blocked.`}
        </p>
        <div className="allowed">
          <span className="allowed-label">Allowed hosts</span>
          <ul>
            {state.allowlist.map((host) => (
              <li key={host}>{host}</li>
            ))}
          </ul>
          <span className="note">Anything else is blocked.</span>
        </div>
        {events.length ? (
          <div className="table-wrap" tabIndex={0} role="group" aria-label="Request log">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Request</th>
                  <th>Sent</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, MAX_ROWS).map((e, i) => (
                  <tr key={`${e.at}-${i}`} className={e.blocked ? "is-blocked" : undefined}>
                    <td className="t-time">{clockTime(e.at)}</td>
                    <td className="t-req">
                      <span className="method">{e.method}</span>
                      {e.host}
                      {e.path}
                    </td>
                    <td className="t-size">{formatBytes(e.bytes_out)}</td>
                    <td className="t-result">{e.blocked ? "Blocked" : String(e.status_code ?? "Failed")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">Nothing has been sent out yet. Requests appear here as Kept reads notes and researches.</p>
        )}
      </div>
    </dialog>
  );
}
