import { isClosed, shorten } from "../selectors";
import { useApp } from "../state";
import type { Commitment, Concern } from "../types";

const SEVERITY_LABEL: Record<Concern["severity"], string> = {
  high: "High risk",
  medium: "Worth a look",
  low: "Minor",
};

function PromiseLink({ promise }: { promise: Commitment }) {
  const { actions } = useApp();
  return (
    <button className="promise-link" type="button" onClick={() => actions.select(promise.id, { scroll: true })}>
      {promise.person}: {shorten(promise.description, 40)}
    </button>
  );
}

export function WeekCheckPanel() {
  const { state, actions } = useApp();
  const open = state.commitments.filter((c) => !isClosed(c));
  if (open.length < 2) return null;

  const byId = new Map(state.commitments.map((c) => [c.id, c]));
  const result = state.weekCheck;
  const working = Boolean(state.busy["week"]);

  return (
    <section className="week-check" aria-labelledby="week-title">
      <div className="section-head">
        <h2 id="week-title">Week check</h2>
        <button
          className={`btn ${result ? "btn-secondary" : "btn-primary"}`}
          type="button"
          disabled={working}
          onClick={() => void actions.checkWeek()}
        >
          {working ? "Reading your week…" : result ? "Check again" : "Check my week"}
        </button>
      </div>

      {working && (
        <div className="working" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <div>
            <p className="working-title">Nemotron Ultra is reading everything you&rsquo;ve promised</p>
            <p className="note">It looks for conflicts and risks. This usually takes about 15 seconds.</p>
          </div>
        </div>
      )}

      {!working && !result && (
        <p className="note">
          Nemotron Ultra reads all your open promises and flags conflicts, late dependencies and anything
          likely to slip, then suggests an order.
        </p>
      )}

      {!working && result && (
        <div className="week-result">
          <p className="week-summary">{result.summary}</p>

          <div className="week-columns">
            <div>
              <h3>{result.concerns.length ? "What to watch" : "Nothing to worry about"}</h3>
              {result.concerns.length > 0 && (
                <ul className="concerns">
                  {result.concerns.map((concern, i) => (
                    <li key={i} className={`concern is-${concern.severity}`}>
                      <p className="concern-severity">{SEVERITY_LABEL[concern.severity]}</p>
                      <p className="concern-title">{concern.title}</p>
                      <p className="note">{concern.explanation}</p>
                      <p className="concern-links">
                        {concern.commitment_ids.map((id) => {
                          const promise = byId.get(id);
                          return promise ? <PromiseLink key={id} promise={promise} /> : null;
                        })}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {result.suggested_order.length > 0 && (
              <div>
                <h3>Suggested order</h3>
                <ol className="order" aria-label="Suggested order">
                  {result.suggested_order.map((item) => {
                    const promise = byId.get(item.commitment_id);
                    return promise ? (
                      <li key={item.commitment_id}>
                        <PromiseLink promise={promise} />
                        <span className="note">{item.reason}</span>
                      </li>
                    ) : null;
                  })}
                </ol>
              </div>
            )}
          </div>

          {result.model_used && <p className="week-credit">Reasoned by {result.model_used} on Nebius Token Factory.</p>}
        </div>
      )}
    </section>
  );
}
