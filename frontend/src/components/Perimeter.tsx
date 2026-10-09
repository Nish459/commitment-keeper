import { clockTime, formatBytes, plural } from "../format";
import { useApp } from "../state";
import { Chevron, ShieldIcon } from "./Seal";

const MAX_ROWS = 60;

export function Perimeter() {
  const { state, actions } = useApp();
  const events = state.audit;
  const blocked = events.filter((e) => e.blocked).length;
  const sent = events.length - blocked;
  const open = state.perimeterOpen;

  const summary = events.length
    ? `${plural(sent, "request")} sent out. ${blocked} blocked.`
    : "Nothing has been sent out yet.";

  return (
    <footer className="perimeter">
      <div
        className="perimeter-panel"
        id="perimeter-panel"
        hidden={!open}
        role="region"
        aria-label="Everything Kept sent out"
      >
        <div className="perimeter-inner">
          <h2>Everything Kept sent out</h2>
          <p className="note">Kept records the host, path and size of every request. Never the content.</p>
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
            <p className="empty">No requests yet. They appear here as Kept reads notes and researches.</p>
          )}
        </div>
      </div>
      <button
        className="perimeter-bar"
        type="button"
        aria-expanded={open}
        aria-controls="perimeter-panel"
        onClick={actions.togglePerimeter}
      >
        <span className="perimeter-icon">
          <ShieldIcon />
        </span>
        <span className="perimeter-summary">
          <strong>Privacy log</strong>
          <span>{summary}</span>
        </span>
        <span className="perimeter-toggle">
          {open ? "Hide details" : "Show details"}
          <Chevron />
        </span>
      </button>
    </footer>
  );
}
