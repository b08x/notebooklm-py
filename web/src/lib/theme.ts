export type Theme = "dark" | "light";
const KEY = "ce-theme";

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/**
 * Flip the theme instantly: transitions are suppressed for one frame so no
 * color cross-fades (inject → force reflow → remove on the next frame).
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.add("theme-switching");
  root.classList.toggle("dark", theme === "dark");
  void root.offsetHeight; // force a reflow with transitions disabled
  requestAnimationFrame(() => root.classList.remove("theme-switching"));
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* not persisted */
  }
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
