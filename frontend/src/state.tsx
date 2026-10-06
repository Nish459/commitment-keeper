import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";

import { api } from "./api";
import { startOfToday } from "./format";
import type { AuditEvent, Capabilities, Commitment, Draft } from "./types";

export type FilterId = "open" | "ready" | "done" | "all";

export interface ToastMessage {
  id: number;
  text: string;
  error: boolean;
}

export interface State {
  commitments: Commitment[];
  drafts: Draft[];
  audit: AuditEvent[];
  allowlist: string[];
  capabilities: Capabilities;
  contacts: Record<string, string>;
  profileName: string;
  profileOpen: boolean;
  selectedId: number | null;
  filter: FilterId;
  busy: Record<string, true>;
  loading: boolean;
  sealedId: number | null;
  perimeterOpen: boolean;
  composer: { open: boolean; sample: boolean };
  toasts: ToastMessage[];
}

export const initialState: State = {
  commitments: [],
  drafts: [],
  audit: [],
  allowlist: [],
  capabilities: { email: { enabled: false, sender: "", recipients: [] } },
  contacts: {},
  profileName: "",
  profileOpen: false,
  selectedId: null,
  filter: "open",
  busy: {},
  loading: true,
  sealedId: null,
  perimeterOpen: false,
  composer: { open: false, sample: false },
  toasts: [],
};

type Action =
  | { type: "loaded"; commitments: Commitment[]; drafts: Draft[]; audit: AuditEvent[] }
  | { type: "setup"; hosts: string[]; capabilities: Capabilities }
  | { type: "contacts"; contacts: Record<string, string> }
  | { type: "profile"; name: string }
  | { type: "profileDialog"; open: boolean }
  | { type: "select"; id: number | null }
  | { type: "filter"; filter: FilterId }
  | { type: "busy"; key: string; value: boolean }
  | { type: "sealed"; id: number | null }
  | { type: "perimeter"; open: boolean }
  | { type: "togglePerimeter" }
  | { type: "composer"; open: boolean; sample?: boolean }
  | { type: "toast"; toast: ToastMessage }
  | { type: "dismissToast"; id: number };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loaded":
      return {
        ...state,
        commitments: action.commitments,
        drafts: action.drafts,
        audit: action.audit,
        loading: false,
      };
    case "setup":
      return { ...state, allowlist: action.hosts, capabilities: action.capabilities };
    case "contacts":
      return { ...state, contacts: action.contacts };
    case "profile":
      return { ...state, profileName: action.name };
    case "profileDialog":
      return { ...state, profileOpen: action.open };
    case "select":
      return { ...state, selectedId: action.id };
    case "filter":
      return { ...state, filter: action.filter };
    case "busy": {
      const { [action.key]: _removed, ...rest } = state.busy;
      return { ...state, busy: action.value ? { ...rest, [action.key]: true } : rest };
    }
    case "sealed":
      return { ...state, sealedId: action.id };
    case "perimeter":
      return { ...state, perimeterOpen: action.open };
    case "togglePerimeter":
      return { ...state, perimeterOpen: !state.perimeterOpen };
    case "composer":
      return { ...state, composer: { open: action.open, sample: action.sample ?? false } };
    case "toast":
      return { ...state, toasts: [...state.toasts, action.toast] };
    case "dismissToast":
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };
  }
}

export interface Actions {
  select: (id: number, options?: { scroll?: boolean }) => void;
  setFilter: (filter: FilterId) => void;
  togglePerimeter: () => void;
  closePerimeter: () => void;
  openComposer: (options?: { sample?: boolean }) => void;
  closeComposer: () => void;
  openProfile: () => void;
  closeProfile: () => void;
  saveProfile: (name: string) => Promise<boolean>;
  dismissToast: (id: number) => void;
  prepare: (commitmentId: number) => Promise<void>;
  saveDraft: (draftId: number, subject: string, body: string) => Promise<boolean>;
  approve: (draftId: number, to?: string) => Promise<void>;
  reject: (draftId: number) => Promise<void>;
  ingest: (name: string, text: string) => Promise<void>;
  copy: (draft: Draft) => Promise<void>;
}

export interface AppContextValue {
  state: State;
  actions: Actions;
  today: Date;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside <AppProvider>");
  return value;
}

let toastId = 0;
const narrow = () => window.matchMedia("(max-width: 62rem)").matches;

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const toast = useCallback((text: string, error = false) => {
    toastId += 1;
    dispatch({ type: "toast", toast: { id: toastId, text, error } });
  }, []);

  const refresh = useCallback(async () => {
    const [commitments, drafts, audit] = await Promise.all([
      api.commitments(),
      api.drafts(),
      api.audit(),
    ]);
    dispatch({ type: "loaded", commitments, drafts, audit });
    return commitments;
  }, []);

  const guarded = useCallback(
    async (work: () => Promise<void>, success?: string) => {
      try {
        await work();
        if (success) toast(success);
      } catch (error) {
        toast(error instanceof Error ? error.message : "Something went wrong.", true);
      }
    },
    [toast],
  );

  const withBusy = useCallback(async (key: string, work: () => Promise<void>) => {
    dispatch({ type: "busy", key, value: true });
    try {
      await work();
    } finally {
      dispatch({ type: "busy", key, value: false });
    }
  }, []);

  const actions = useMemo<Actions>(
    () => ({
      select(id, { scroll = false } = {}) {
        dispatch({ type: "select", id });
        if (scroll && narrow()) {
          document.getElementById("detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      },
      setFilter: (filter) => dispatch({ type: "filter", filter }),
      togglePerimeter: () => dispatch({ type: "togglePerimeter" }),
      closePerimeter: () => dispatch({ type: "perimeter", open: false }),
      openComposer: (options) => dispatch({ type: "composer", open: true, sample: options?.sample }),
      closeComposer: () => dispatch({ type: "composer", open: false }),
      openProfile: () => dispatch({ type: "profileDialog", open: true }),
      closeProfile: () => dispatch({ type: "profileDialog", open: false }),
      async saveProfile(name) {
        try {
          const saved = await api.saveProfile(name);
          dispatch({ type: "profile", name: saved.name });
          toast(saved.name ? `Emails will be signed ${saved.name}.` : "Name cleared.");
          return true;
        } catch (error) {
          toast(error instanceof Error ? error.message : "Something went wrong.", true);
          return false;
        }
      },
      dismissToast: (id) => dispatch({ type: "dismissToast", id }),

      async prepare(commitmentId) {
        dispatch({ type: "select", id: commitmentId });
        dispatch({ type: "sealed", id: null });
        await withBusy(String(commitmentId), () =>
          guarded(async () => {
            await api.prepare(commitmentId);
            await refresh();
            dispatch({ type: "sealed", id: commitmentId });
            setTimeout(() => dispatch({ type: "sealed", id: null }), 1600);
          }, "Draft ready for your review."),
        );
        await refresh().catch(() => undefined);
      },

      async saveDraft(draftId, subject, body) {
        try {
          await api.updateDraft(draftId, subject, body);
          await refresh();
          toast("Draft saved.");
          return true;
        } catch (error) {
          toast(error instanceof Error ? error.message : "Something went wrong.", true);
          return false;
        }
      },

      approve: (draftId, to) =>
        withBusy(`draft-${draftId}`, () =>
          guarded(
            async () => {
              await api.approve(draftId, to);
              await refresh();
              if (to) dispatch({ type: "contacts", contacts: await api.contacts() });
            },
            to ? `Email sent to ${to}. Marked as kept.` : "Approved. Marked as kept.",
          ),
        ),

      reject: (draftId) =>
        withBusy(`draft-${draftId}`, () =>
          guarded(async () => {
            await api.reject(draftId);
            await refresh();
          }, "Draft rejected."),
        ),

      async ingest(name, text) {
        const found = await api.ingest(name, text);
        await refresh();
        const [first] = found;
        if (first) dispatch({ type: "select", id: first.id });
        toast(
          found.length === 0
            ? "No promises found in that note."
            : `Found ${found.length === 1 ? "1 promise" : `${found.length} promises`}.`,
        );
      },

      copy: (draft) =>
        guarded(
          () => navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.body}`),
          "Email copied.",
        ),
    }),
    [guarded, refresh, toast, withBusy],
  );

  useEffect(() => {
    void guarded(async () => {
      const [hosts, capabilities, contacts, profile, commitments] = await Promise.all([
        api.allowlist(),
        api.capabilities(),
        api.contacts(),
        api.profile(),
        refresh(),
      ]);
      dispatch({ type: "profile", name: profile.name });
      dispatch({ type: "setup", hosts, capabilities });
      dispatch({ type: "contacts", contacts });
      const first = commitments.find((c) => c.status === "ready_for_review") ?? commitments[0];
      if (first) dispatch({ type: "select", id: first.id });
    });
  }, [guarded, refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dispatch({ type: "perimeter", open: false });
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo(() => ({ state, actions, today: startOfToday() }), [state, actions]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
