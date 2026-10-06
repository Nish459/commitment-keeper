import type { CommitmentStatus } from "../types";

export const SEAL_LABEL: Record<CommitmentStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  ready_for_review: "Draft ready",
  done: "Kept",
  dropped: "Dropped",
};

const SHAPES: Record<CommitmentStatus, React.ReactNode> = {
  open: <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.75" />,
  in_progress: (
    <>
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />
    </>
  ),
  ready_for_review: (
    <>
      <circle cx="8" cy="8" r="7" fill="currentColor" />
      <circle className="seal-ink" cx="8" cy="8" r="3.2" fill="none" strokeWidth="1.5" />
    </>
  ),
  done: (
    <>
      <circle cx="8" cy="8" r="7" fill="currentColor" />
      <path
        d="M4.8 8.3 7 10.4l4.2-4.8"
        fill="none"
        className="seal-ink"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),
  dropped: (
    <>
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path d="m4.5 11.5 7-7" stroke="currentColor" strokeWidth="1.75" />
    </>
  ),
};

/** A status seal. Color comes from the surrounding element via currentColor. */
export function Seal({ status, stamp = false }: { status: CommitmentStatus; stamp?: boolean }) {
  return (
    <svg
      className={`seal seal-${status}${stamp ? " seal-stamp" : ""}`}
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      {SHAPES[status]}
    </svg>
  );
}

export function ShieldIcon() {
  return (
    <svg className="shield" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 1.5 2.5 3.6v4.1c0 3.2 2.3 5.7 5.5 6.8 3.2-1.1 5.5-3.6 5.5-6.8V3.6z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="m5.6 8.1 1.7 1.7 3.2-3.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Chevron() {
  return (
    <svg className="chevron" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="m4 10 4-4 4 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
