import { dueLabel, plural } from "../format";
import { byDue, directionLabel, isClosed, isOverdue } from "../selectors";
import { useApp, type FilterId } from "../state";
import type { Commitment } from "../types";
import { Seal, SEAL_LABEL } from "./Seal";

export const FILTERS: { id: FilterId; label: string; test: (c: Commitment) => boolean }[] = [
  { id: "open", label: "Open", test: (c) => !isClosed(c) },
  { id: "ready", label: "Draft ready", test: (c) => c.status === "ready_for_review" },
  { id: "done", label: "Kept", test: (c) => c.status === "done" },
  { id: "all", label: "All", test: () => true },
];

function Row({ c }: { c: Commitment }) {
  const { state, actions, today } = useApp();
  return (
    <li>
      <button
        type="button"
        className="row"
        data-status={c.status}
        aria-pressed={state.selectedId === c.id}
        onClick={() => actions.select(c.id, { scroll: true })}
      >
        <Seal status={c.status} stamp={state.sealedId === c.id} />
        <span className="row-body">
          <span className="row-title">{c.description}</span>
          <span className="row-meta">
            <span>{directionLabel(c)}</span>
            <span className={isOverdue(c, today) ? "is-overdue" : undefined}>{dueLabel(c.due, today)}</span>
          </span>
        </span>
        <span className="row-status">{SEAL_LABEL[c.status]}</span>
      </button>
    </li>
  );
}

export function Ledger() {
  const { state, actions } = useApp();
  const active = FILTERS.find((f) => f.id === state.filter) ?? FILTERS[0]!;
  const filtered = state.commitments.filter(active.test).sort(byDue);

  const groups = new Map<string, Commitment[]>();
  for (const c of filtered) groups.set(c.person, [...(groups.get(c.person) ?? []), c]);

  return (
    <section className="ledger" id="ledger" aria-labelledby="ledger-title">
      <div className="section-head">
        <h2 id="ledger-title">Ledger</h2>
        <div className="filters" role="group" aria-label="Filter promises">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className="chip"
              aria-pressed={f.id === active.id}
              onClick={() => actions.setFilter(f.id)}
            >
              {f.label}
              <span className="chip-count">{state.commitments.filter(f.test).length}</span>
            </button>
          ))}
        </div>
      </div>

      {groups.size === 0 ? (
        <p className="empty">
          {state.commitments.length
            ? `No ${active.label.toLowerCase()} promises. ${plural(state.commitments.length, "promise")} tracked in total.`
            : "Promises Kept finds will be listed here, grouped by person."}
        </p>
      ) : (
        [...groups].map(([person, items]) => {
          const mine = items.filter((c) => c.direction === "owed_by_me").length;
          const theirs = items.length - mine;
          const counts = [mine && `${mine} you owe`, theirs && `${theirs} owes you`].filter(Boolean).join(", ");
          return (
            <section className="group" key={person} aria-label={person}>
              <h3 className="group-title">
                {person}
                <span className="group-count">{counts}</span>
              </h3>
              <ul className="rows">
                {items.map((c) => (
                  <Row key={c.id} c={c} />
                ))}
              </ul>
            </section>
          );
        })
      )}
    </section>
  );
}
