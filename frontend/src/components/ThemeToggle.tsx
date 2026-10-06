import { useTheme } from "../theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const label = dark ? "Switch to the light theme" : "Switch to the dark theme";
  return (
    <button className="theme-toggle" type="button" aria-label={label} title={label} onClick={toggle}>
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {dark ? (
          <>
            <circle cx="10" cy="10" r="3.6" fill="currentColor" />
            <path
              d="M10 2.2v2M10 15.8v2M2.2 10h2M15.8 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M4.5 15.5l1.4-1.4M14.1 5.9l1.4-1.4"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              fill="none"
            />
          </>
        ) : (
          <path
            d="M16.2 12.4A6.8 6.8 0 0 1 7.6 3.8a6.8 6.8 0 1 0 8.6 8.6z"
            fill="currentColor"
          />
        )}
      </svg>
    </button>
  );
}
