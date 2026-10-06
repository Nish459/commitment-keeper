import { useEffect, useRef, useState } from "react";

import { formatBytes } from "../format";
import { useApp } from "../state";
import type { Draft } from "../types";

/** Files that travel with the email. Needed when the email says "attached". */
export function Attachments({ draft }: { draft: Draft }) {
  const { state, actions } = useApp();
  const { email } = state.capabilities;
  const files = state.attachments[draft.id] ?? [];
  const pending = draft.status === "pending";
  const picker = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (email.enabled) void actions.loadAttachments(draft.id);
  }, [actions, draft.id, email.enabled]);

  if (!email.enabled) {
    return pending && draft.needs_attachment ? (
      <p className="note attach-warning">
        This email says a file is attached. Sending is off, so copy the text and attach the file in your own
        mail app, or add your SMTP settings to <code>.env</code> to send it from here.
      </p>
    ) : null;
  }
  if (!pending && files.length === 0) return null;

  return (
    <section className="attachments" aria-label="Attachments">
      <div className="attachments-head">
        <h4>{pending ? "Attachments" : "Sent with"}</h4>
        {pending && (
          <>
            <button
              className="btn btn-secondary"
              type="button"
              disabled={uploading}
              onClick={() => picker.current?.click()}
            >
              {uploading ? "Adding…" : files.length ? "Add more files" : "Add files"}
            </button>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              aria-label="Choose files to attach"
              onChange={(event) => {
                const chosen = Array.from(event.target.files ?? []);
                event.target.value = "";
                if (!chosen.length) return;
                setUploading(true);
                void actions.addAttachments(draft.id, chosen).finally(() => setUploading(false));
              }}
            />
          </>
        )}
      </div>

      {pending && draft.needs_attachment && files.length === 0 && (
        <p className="note attach-warning" role="status">
          This email says a file is attached. Add it before sending.
        </p>
      )}

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((file) => (
            <li key={file.id}>
              <span className="file-name">{file.filename}</span>
              <span className="file-size">{formatBytes(file.size)}</span>
              {pending && (
                <button
                  className="btn btn-quiet"
                  type="button"
                  aria-label={`Remove ${file.filename}`}
                  onClick={() => void actions.removeAttachment(draft.id, file.id)}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
