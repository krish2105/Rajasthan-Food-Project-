import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(cleanup);

// jsdom implements neither, and both are read during render.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

// jsdom has no IntersectionObserver. The reveal hook must degrade to showing
// content rather than hiding it, which is what these tests check.
if (!("IntersectionObserver" in window)) {
  vi.stubGlobal("IntersectionObserver", undefined);
}
