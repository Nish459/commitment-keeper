import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { InfoIcon } from "./Seal";

/**
 * A small "i" that explains something on demand. It opens on click or tap (not only on hover, so
 * phones and keyboards work), closes on Escape or a click elsewhere, and returns focus to the icon.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    const onPress = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!tip.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPress);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPress);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        className="info-button"
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((current) => !current)}
      >
        <InfoIcon />
      </button>
      <div ref={tip} id={id} className="info-tip" role="note" hidden={!open}>
        {children}
      </div>
    </>
  );
}
