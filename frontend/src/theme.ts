import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "kept-theme";
const COLORS: Record<Theme, string> = { light: "#f3f5f7", dark: "#101012" };

// The same rule runs inline in index.html before first paint, so the page never flashes the wrong theme.
export function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function storedTheme(): Theme | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    return null; // private windows and blocked storage must not break the app
  }
}

function remember(theme: Theme | null) {
  try {
    if (theme) localStorage.setItem(STORAGE_KEY, theme);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Not persisting is fine; the choice still applies for this visit.
  }
}

/** Switch the palette. Transitions are paused for a frame so hundreds of elements don't animate at once. */
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.add("theme-switching");
  root.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", COLORS[theme]);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  // Until the user chooses, follow the operating system, including when it changes mid-visit.
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (storedTheme()) return;
      const next = systemTheme();
      setTheme(next);
      applyTheme(next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    // Choosing the system's own theme means "follow the system", so don't pin it.
    remember(next === systemTheme() ? null : next);
    setTheme(next);
    applyTheme(next);
  }, [theme]);

  return { theme, toggle };
}
