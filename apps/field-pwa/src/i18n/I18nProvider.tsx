import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { type Lang, type StringKey, strings, translate } from "./strings";

/**
 * Language state.
 *
 * Hindi is the default with no negotiation against the browser locale. Section
 * 9.1 says Hindi primary, English secondary; a worker on a phone shipped with
 * an English locale should still open the app in Hindi. English is a choice
 * they make, not a default they have to undo.
 *
 * The choice lives in localStorage rather than on the server, because the app
 * must come up in the right language on a cold start with no signal.
 */

const STORAGE_KEY = "poshannetra.lang";

interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: StringKey) => string;
  /** The other language's rendering, for secondary captions. */
  alt: (key: StringKey) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function readStored(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "en" ? "en" : "hi";
  } catch {
    // Private browsing, or storage disabled. Hindi is the right fallback.
    return "hi";
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStored);

  useEffect(() => {
    // Keeps screen readers and font selection correct: `lang` drives which
    // voice and which font stack the OS picks for the subtree.
    document.documentElement.lang = lang === "hi" ? "hi" : "en";
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A worker who cannot persist the choice should still get the switch
      // for this session rather than a dead control.
    }
  }, []);

  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      t: (key) => translate(key, lang),
      alt: (key) => strings[key][lang === "hi" ? "en" : "hi"],
    }),
    [lang, setLang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}
