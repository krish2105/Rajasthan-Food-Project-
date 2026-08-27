import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

/**
 * Theme state: light, dark, system, and sunlight.
 *
 * `sunlight` is the one that is not conventional, and it is the one that earns
 * its place. This app is used outdoors in Rajasthan on a budget LCD panel at
 * a few hundred nits. A normal light theme in that setting is not merely
 * uncomfortable, it is unreadable, and a worker who cannot read the screen
 * cannot confirm which child they just photographed.
 *
 * `system` is a distinct stored value rather than the absence of one, so that
 * "follow my phone" survives a reload. An explicit choice always beats the OS
 * preference -- a phone that flips to dark at dusk should not override a
 * worker who is still standing in the sun.
 */

export type Theme = "light" | "dark" | "system" | "sunlight";

const STORAGE_KEY = "poshannetra.theme";
const THEMES: readonly Theme[] = ["light", "dark", "system", "sunlight"] as const;

/** Matches the <meta name="theme-color"> values so the OS chrome agrees. */
const THEME_COLORS: Record<Exclude<Theme, "system">, string> = {
  light: "#f8fafc",
  dark: "#0b1220",
  sunlight: "#ffffff",
};

interface ThemeValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** What is actually painted once `system` is resolved. */
  resolved: Exclude<Theme, "system">;
}

const ThemeContext = createContext<ThemeValue | null>(null);

function readStored(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(stored as Theme) ? (stored as Theme) : "system";
  } catch {
    return "system";
  }
}

function prefersDark(): boolean {
  // Guarded rather than assumed. Some older Android WebViews expose
  // matchMedia but return undefined for an unrecognised feature query, so
  // reading `.matches` straight off the result throws on exactly the devices
  // this app targets -- and a theme lookup must never take the app down.
  try {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-color-scheme: dark)")?.matches === true;
  } catch {
    return false;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStored);
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    // addEventListener is not present on older Android WebViews, which are
    // exactly the devices this app targets.
    if (query.addEventListener) {
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    }
    query.addListener(onChange);
    return () => query.removeListener(onChange);
  }, []);

  const resolved: Exclude<Theme, "system"> =
    theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") {
      // Removing the attribute hands control to the prefers-color-scheme
      // media query in tokens.css, so there is exactly one place that decides.
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", theme);
    }
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]:not([media])');
    if (meta) meta.content = THEME_COLORS[resolved];
  }, [theme, resolved]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Non-persistent is better than non-functional.
    }
  }, []);

  const value = useMemo<ThemeValue>(
    () => ({ theme, setTheme, resolved }),
    [theme, setTheme, resolved],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
