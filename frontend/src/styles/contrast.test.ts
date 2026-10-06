import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** A guard on the design tokens: every text and control color must stay readable in BOTH themes. */
const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "tokens.css"), "utf8");

function tokens(selector: RegExp): Record<string, string> {
  const block = selector.exec(css)?.[1] ?? "";
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1]!, m[2]!]));
}

const light = tokens(/:root\s*\{([\s\S]*?)\n\}/);
const dark = { ...light, ...tokens(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/) };

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

// [foreground, background]. Text needs 4.5:1 (WCAG AA). Controls, focus rings and icons need 3:1.
const TEXT: [string, string][] = [
  ["ink", "paper"], ["ink", "surface"], ["ink", "today-wash"], ["muted", "today-wash"],
  ["cobalt-ink", "today-wash"], ["muted", "paper"], ["muted", "surface"],
  ["cobalt-ink", "surface"], ["cobalt-ink", "paper"], ["cobalt-ink", "cobalt-wash"],
  ["kept", "surface"], ["kept", "kept-wash"], ["seal", "surface"], ["seal", "seal-wash"],
  ["on-cobalt", "cobalt"], ["on-cobalt", "cobalt-strong"],
  ["on-inverse", "inverse"], ["on-inverse-muted", "inverse"],
  ["bar-text", "bar-bg"], ["bar-muted", "bar-bg"], ["bar-accent", "bar-bg"],
  ["placeholder", "paper"], ["placeholder", "surface"],
]; // prettier-ignore
const UI: [string, string][] = [
  ["focus", "paper"], ["focus", "surface"], ["control-border", "surface"], ["control-border", "paper"],
  ["cobalt-icon", "surface"], ["cobalt-icon", "cobalt-wash"], ["kept", "surface"], ["seal", "surface"],
  ["rule", "paper"], ["on-icon", "cobalt-icon"], ["on-icon", "kept"],
]; // prettier-ignore

describe.each([
  ["light", light],
  ["dark", dark],
] as const)("%s theme", (_name, theme) => {
  it("defines every token the checks use", () => {
    for (const [fg, bg] of [...TEXT, ...UI]) {
      expect(theme[fg], `--${fg}`).toBeDefined();
      expect(theme[bg], `--${bg}`).toBeDefined();
    }
  });

  it.each(TEXT)("text --%s on --%s has at least 4.5:1", (fg, bg) => {
    expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(UI)("control or icon --%s on --%s has at least 3:1", (fg, bg) => {
    expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(3);
  });
});

it("overrides colors only: the dark block defines no sizes, fonts or spacing", () => {
  const block = /:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? "";
  expect(block).not.toMatch(/--(font|step|s|r)-/);
});
