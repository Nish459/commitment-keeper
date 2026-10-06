import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "./components/ThemeToggle";
import { storedTheme, systemTheme, useTheme } from "./theme";

type Listener = () => void;

/** A controllable stand-in for the operating system's color scheme. */
function mockSystem(initial: "light" | "dark") {
  let dark = initial === "dark";
  const listeners = new Set<Listener>();
  window.matchMedia = ((query: string) => ({
    get matches() {
      return query.includes("dark") ? dark : !dark;
    },
    media: query,
    addEventListener: (_: string, fn: Listener) => listeners.add(fn),
    removeEventListener: (_: string, fn: Listener) => listeners.delete(fn),
  })) as unknown as typeof window.matchMedia;
  return {
    switchTo(next: "light" | "dark") {
      dark = next === "dark";
      listeners.forEach((fn) => fn());
    },
  };
}

function Probe() {
  const { theme, toggle } = useTheme();
  return (
    <button type="button" onClick={toggle}>
      {theme}
    </button>
  );
}

beforeEach(() => {
  document.head.insertAdjacentHTML("beforeend", '<meta name="theme-color" content="#f3f5f7">');
});
afterEach(() => {
  document.querySelector('meta[name="theme-color"]')?.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("theme choice", () => {
  it("follows the system when nothing was chosen", () => {
    mockSystem("dark");
    expect(systemTheme()).toBe("dark");
    render(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("dark");
  });

  it("lets a saved choice beat the system", () => {
    mockSystem("dark");
    localStorage.setItem("kept-theme", "light");
    render(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("light");
  });

  it("ignores junk in storage", () => {
    mockSystem("light");
    localStorage.setItem("kept-theme", "purple");
    expect(storedTheme()).toBeNull();
    render(<Probe />);
    expect(screen.getByRole("button")).toHaveTextContent("light");
  });

  it("switches the palette, the browser chrome color, and remembers an explicit choice", async () => {
    mockSystem("light");
    render(<Probe />);
    await userEvent.click(screen.getByRole("button"));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.querySelector('meta[name="theme-color"]')).toHaveAttribute("content", "#0d1322");
    expect(localStorage.getItem("kept-theme")).toBe("dark");
  });

  it("stops pinning the choice once it matches the system again, so the system keeps leading", async () => {
    mockSystem("light");
    render(<Probe />);
    await userEvent.click(screen.getByRole("button"));
    expect(localStorage.getItem("kept-theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button"));
    expect(localStorage.getItem("kept-theme")).toBeNull();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("follows a system change mid-visit, but only while the user has not chosen", () => {
    const system = mockSystem("light");
    render(<Probe />);
    act(() => system.switchTo("dark"));
    expect(screen.getByRole("button")).toHaveTextContent("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    localStorage.setItem("kept-theme", "dark");
    act(() => system.switchTo("light"));
    expect(screen.getByRole("button")).toHaveTextContent("dark");
  });

  it("still works when storage is blocked", async () => {
    mockSystem("light");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<Probe />);
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("pauses transitions for the swap only", async () => {
    mockSystem("light");
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    render(<Probe />);
    act(() => screen.getByRole("button").click());
    expect(document.documentElement).toHaveClass("theme-switching");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(document.documentElement).not.toHaveClass("theme-switching");
  });
});

describe("ThemeToggle", () => {
  it("names the action it will take, not the state it is in", async () => {
    mockSystem("light");
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Switch to the dark theme" });
    await userEvent.click(button);
    expect(screen.getByRole("button", { name: "Switch to the light theme" })).toBeInTheDocument();
  });
});
