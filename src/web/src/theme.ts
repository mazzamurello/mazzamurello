// Light and dark themes: the device's choice unless the user picks one (UX-011, ADR-0070).
import { useCallback, useState } from "react";

export type Theme = "system" | "light" | "dark";

const KEY = "sibillo.theme";

function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

/** Set the theme on the document; `system` leaves it to the device. */
export function applyTheme(theme: Theme = stored()): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(stored);
  const choose = useCallback((next: Theme) => {
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // A browser that keeps nothing still shows the theme until the next visit.
    }
    applyTheme(next);
    setTheme(next);
  }, []);
  return [theme, choose];
}
