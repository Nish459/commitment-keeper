import { Composer } from "./components/Composer";
import { Detail } from "./components/Detail";
import { Hero } from "./components/Hero";
import { Ledger } from "./components/Ledger";
import { Perimeter } from "./components/Perimeter";
import { Timeline } from "./components/Timeline";
import { Toasts } from "./components/Toasts";
import { useApp } from "./state";

export function App() {
  const { actions } = useApp();
  return (
    <>
      <a className="skip" href="#ledger">
        Skip to the ledger
      </a>
      <header className="topbar">
        <div className="wordmark" aria-label="Kept">
          <svg className="wordmark-seal" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r="7" fill="currentColor" />
            <circle cx="8" cy="8" r="3.2" fill="none" stroke="#fff" strokeWidth="1.5" />
          </svg>
          <span>Kept</span>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => actions.openComposer()}>
          Add notes
        </button>
      </header>
      <main className="page">
        <Hero />
        <Timeline />
        <div className="split">
          <Ledger />
          <Detail />
        </div>
      </main>
      <Perimeter />
      <Composer />
      <Toasts />
    </>
  );
}
