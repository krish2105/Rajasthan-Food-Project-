import { describe, expect, it } from "vitest";
import { strings, translate } from "../src/i18n/strings";

/**
 * Bilingual completeness.
 *
 * Section 9.1 asks for a Hindi-first bilingual UI. The failure mode this file
 * guards against is the ordinary one: a string gets added in English, the Hindi
 * is left as a placeholder or a copy, and a Hindi-first worker meets an English
 * label in the middle of their own interface. That is invisible to anyone
 * reviewing in English, so it is asserted mechanically.
 */

const entries = Object.entries(strings);
/** Devanagari block. */
const DEVANAGARI = /[ऀ-ॿ]/;
/** Keys that are legitimately identical in both languages. */
const PROPER_NOUNS = new Set(["languageHindi", "languageEnglish"]);

describe("bilingual string table", () => {
  it("has a non-empty Hindi and English value for every key", () => {
    for (const [key, value] of entries) {
      expect(value.hi, `${key}.hi is empty`).toBeTruthy();
      expect(value.en, `${key}.en is empty`).toBeTruthy();
    }
  });

  it("has genuine Devanagari in every Hindi string", () => {
    const missing = entries
      .filter(([key]) => !PROPER_NOUNS.has(key))
      .filter(([, value]) => !DEVANAGARI.test(value.hi))
      .map(([key]) => key);
    expect(missing, "Hindi values without Devanagari (untranslated?)").toEqual([]);
  });

  it("never leaves the Hindi value as a copy of the English one", () => {
    const copied = entries
      .filter(([key]) => !PROPER_NOUNS.has(key))
      .filter(([, value]) => value.hi === value.en)
      .map(([key]) => key);
    expect(copied, "keys where Hindi is a copy of English").toEqual([]);
  });

  it("keeps English strings free of Devanagari", () => {
    const leaked = entries
      .filter(([key]) => !PROPER_NOUNS.has(key))
      .filter(([, value]) => DEVANAGARI.test(value.en))
      .map(([key]) => key);
    expect(leaked).toEqual([]);
  });

  it("translates in both directions", () => {
    expect(translate("navHome", "hi")).toBe("मुख्य");
    expect(translate("navHome", "en")).toBe("Home");
  });

  it("covers every classification the backend can return", () => {
    // Section 5's CHECK constraint vocabulary. A status the server can send but
    // the app cannot name would render as a blank in front of a worker.
    for (const key of ["classNormal", "classMam", "classSam", "classStunted", "classUnderweight"] as const) {
      expect(strings[key].hi).toBeTruthy();
    }
  });

  it("explains offline behaviour rather than only announcing it", () => {
    // A worker with no signal needs to be told their work is safe, not left to
    // infer it from the absence of an error.
    expect(strings.captureSavedDetail.hi).toMatch(/फ़ोन|सुरक्षित/);
    expect(strings.offlineDetail.hi).toMatch(/सुरक्षित|अपने आप/);
  });
});
