import { useApp } from "../state";

export function DemoBanner() {
  const { state } = useApp();
  if (!state.capabilities.demo) return null;
  return (
    <aside className="demo-banner" aria-label="About this demo">
      <p>
        <strong>This is a demo workspace.</strong> It&rsquo;s private to this browser, comes with sample promises,
        and resets after a couple of hours. Email sending is off, and usage is capped.
      </p>
    </aside>
  );
}
