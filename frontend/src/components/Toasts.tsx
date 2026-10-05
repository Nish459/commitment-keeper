import { useEffect } from "react";

import { useApp, type ToastMessage } from "../state";

function ToastItem({ toast }: { toast: ToastMessage }) {
  const { actions } = useApp();
  useEffect(() => {
    const timer = setTimeout(() => actions.dismissToast(toast.id), toast.error ? 9000 : 4000);
    return () => clearTimeout(timer);
  }, [actions, toast.id, toast.error]);
  return <div className={`toast${toast.error ? " is-error" : ""}`}>{toast.text}</div>;
}

export function Toasts() {
  const { state } = useApp();
  return (
    <div className="toasts" role="status" aria-live="polite">
      {state.toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>
  );
}
