import { useEffect, useRef, useState, type FormEvent } from "react";

import { useApp } from "../state";

export function ProfileDialog() {
  const { state, actions } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(state.profileName);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (state.profileOpen && !el.open) {
      setName(state.profileName);
      el.showModal();
    } else if (!state.profileOpen && el.open) {
      el.close();
    }
  }, [state.profileOpen, state.profileName]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    const saved = await actions.saveProfile(name.trim());
    setSaving(false);
    if (saved) actions.closeProfile();
  }

  return (
    <dialog ref={dialog} className="composer" aria-labelledby="profile-title" onClose={actions.closeProfile}>
      <form className="composer-form" onSubmit={(e) => void submit(e)}>
        <h2 id="profile-title">Your name</h2>
        <p className="note">
          Kept signs emails with this name, under &ldquo;Best,&rdquo;. It&rsquo;s stored only on this
          machine.
        </p>
        <label className="field">
          <span>Name</span>
          <input
            maxLength={100}
            value={name}
            placeholder="Your full name"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <div className="composer-actions">
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save name"}
          </button>
          <button className="btn btn-secondary" type="button" disabled={saving} onClick={actions.closeProfile}>
            Cancel
          </button>
        </div>
      </form>
    </dialog>
  );
}
