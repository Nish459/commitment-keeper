import { Composer } from "./components/Composer";
import { DemoBanner } from "./components/DemoBanner";
import { Detail } from "./components/Detail";
import { Hero } from "./components/Hero";
import { Ledger } from "./components/Ledger";
import { PrivacyLog, PrivacyLogButton } from "./components/PrivacyLog";
import { ProfileDialog } from "./components/ProfileDialog";
import { Timeline } from "./components/Timeline";
import { ThemeToggle } from "./components/ThemeToggle";
import { Toasts } from "./components/Toasts";
import { WeekCheckPanel } from "./components/WeekCheckPanel";
import { useApp } from "./state";

export function App() {
  const { state, actions } = useApp();
  return (
    <>
      <a className="skip" href="#ledger">
        Skip to the ledger
      </a>
      <header className="topbar">
        <div className="wordmark" aria-label="Kept">
          <svg className="wordmark-seal" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r="7" fill="currentColor" />
            <circle className="seal-ink" cx="8" cy="8" r="3.2" fill="none" strokeWidth="1.5" />
          </svg>
          <span>Kept</span>
        </div>
        <div className="topbar-actions">
          <PrivacyLogButton />
          <ThemeToggle />
          <button className="btn btn-quiet profile-button" type="button" onClick={actions.openProfile}>
            {state.profileName ? `Signing as ${state.profileName}` : "Add your name"}
          </button>
          <button className="btn btn-primary" type="button" onClick={() => actions.openComposer()}>
            Add promises
          </button>
        </div>
      </header>
      <main className="page">
        <DemoBanner />
        <Hero />
        <Timeline />
        <WeekCheckPanel />
        <div className="split">
          <Ledger />
          <Detail />
        </div>
      </main>
      <PrivacyLog />
      <Composer />
      <ProfileDialog />
      <Toasts />
    </>
  );
}
