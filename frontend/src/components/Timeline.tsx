import { addDays, dayDiff, dayMonthName, dueLabel, toISO, weekdayName } from "../format";
import { isOverdue, shorten } from "../selectors";
import { useApp } from "../state";
import type { Commitment } from "../types";
import { Seal, SEAL_LABEL } from "./Seal";

const DAYS_SHOWN = 7;

interface Column {
  key: string;
  title: string;
  sub?: string;
  items: Commitment[];
  today?: boolean;
  weekend?: boolean;
  overdue?: boolean;
}

export function buildColumns(commitments: Commitment[], today: Date): Column[] {
  const visible = commitments.filter(
    (c) => c.status !== "dropped" && !(c.status === "done" && c.due && dayDiff(c.due, today) < 0),
  );
  const columns: Column[] = [];

  const overdue = visible.filter((c) => isOverdue(c, today));
  if (overdue.length) columns.push({ key: "overdue", title: "Overdue", items: overdue, overdue: true });

  for (let i = 0; i < DAYS_SHOWN; i += 1) {
    const date = addDays(today, i);
    const iso = toISO(date);
    columns.push({
      key: iso,
      title: i === 0 ? "Today" : weekdayName(date),
      sub: dayMonthName(date),
      today: i === 0,
      weekend: date.getDay() === 0 || date.getDay() === 6,
      items: visible.filter((c) => c.due === iso),
    });
  }

  const later = visible.filter((c) => c.due && dayDiff(c.due, today) >= DAYS_SHOWN);
  if (later.length) columns.push({ key: "later", title: "Later", items: later });
  const undated = visible.filter((c) => !c.due);
  if (undated.length) columns.push({ key: "undated", title: "No date", items: undated });
  return columns;
}

const GUTTER_REM = 5;

/** Populated days get room for text; empty days thin out so the week still reads as a week. */
function columnSizing(columns: Column[]): React.CSSProperties {
  const sizes = columns.map((col) => {
    if (col.items.length) return { min: 9.5, fr: 1.6 };
    return col.today ? { min: 6.5, fr: 0.8 } : { min: 3.5, fr: 0.45 };
  });
  const track = sizes.map(({ min, fr }) => `minmax(${min}rem, ${fr}fr)`).join(" ");
  const minWidth = GUTTER_REM + sizes.reduce((sum, { min }) => sum + min, 0);
  return { gridTemplateColumns: `${GUTTER_REM}rem ${track}`, minWidth: `${minWidth}rem` };
}

function Token({ c }: { c: Commitment }) {
  const { state, actions, today } = useApp();
  const overdue = isOverdue(c, today);
  return (
    <button
      type="button"
      className={`token${overdue ? " is-overdue" : ""}`}
      data-status={c.status}
      aria-pressed={state.selectedId === c.id}
      aria-label={`${c.person}: ${c.description}. ${dueLabel(c.due, today)}. ${SEAL_LABEL[c.status]}.`}
      onClick={() => actions.select(c.id)}
    >
      <Seal status={c.status} stamp={state.sealedId === c.id} />
      <span className="token-text">
        <span className="token-person">{c.person}</span>
        <span className="token-desc">{shorten(c.description, 60)}</span>
      </span>
    </button>
  );
}

function DayColumn({ col }: { col: Column }) {
  const mine = col.items.filter((c) => c.direction === "owed_by_me");
  const theirs = col.items.filter((c) => c.direction === "owed_to_me");
  const classes = [
    "col",
    col.today && "is-today",
    col.weekend && "is-weekend",
    col.overdue && "is-overdue",
    col.items.length === 0 && "is-empty",
  ];
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      role="group"
      aria-label={col.sub ? `${col.title} ${col.sub}` : col.title}
    >
      <div className="above">
        {mine.map((c) => (
          <Token key={c.id} c={c} />
        ))}
      </div>
      <div className="axis">
        <span className="axis-label">
          <span className="ax-day">{col.title}</span>
          {col.sub && <span className="ax-date">{col.sub}</span>}
        </span>
      </div>
      <div className="below">
        {theirs.map((c) => (
          <Token key={c.id} c={c} />
        ))}
      </div>
    </div>
  );
}

export function Timeline() {
  const { state, today } = useApp();
  const columns = buildColumns(state.commitments, today);
  return (
    <section className="line" aria-labelledby="line-title">
      <div className="section-head">
        <h2 id="line-title">Due dates</h2>
        <ul className="legend" aria-label="Seal key">
          {(["open", "ready_for_review", "done"] as const).map((status) => (
            <li key={status} className={`legend-item seal-tone-${status}`}>
              <Seal status={status} />
              {SEAL_LABEL[status]}
            </li>
          ))}
        </ul>
      </div>
      <div className="line-scroll">
        <div className="line-grid" style={columnSizing(columns)}>
          <div className="gutter">
            <span className="gutter-above">You owe</span>
            <span className="gutter-axis" />
            <span className="gutter-below">Owed to you</span>
          </div>
          {columns.map((col) => (
            <DayColumn key={col.key} col={col} />
          ))}
        </div>
      </div>
    </section>
  );
}
