import "@testing-library/jest-dom/vitest";
import "fake-indexeddb/auto";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { closeDb } from "../src/db/schema";

/**
 * Each test gets a clean IndexedDB and a clean localStorage.
 *
 * The offline queue is the app's source of truth, so a test that inherited
 * another test's queue would be testing a state no device ever reaches.
 */
beforeEach(async () => {
  const { indexedDB } = await import("fake-indexeddb");
  // Close first. IndexedDB refuses to delete a database while a connection is
  // open -- the request fires `blocked` and never completes, which hangs the
  // whole suite rather than failing it.
  await closeDb();
  await new Promise<void>((resolve) => {
    const request = indexedDB.deleteDatabase("poshannetra");
    request.onsuccess = () => resolve();
    request.onerror = () => resolve();
    request.onblocked = () => resolve();
  });
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * jsdom implements neither, and both are load-bearing here.
 *
 * Plain functions, deliberately not vi.fn(). `vi.restoreAllMocks()` in the
 * shared afterEach resets vi.fn implementations, which would leave these
 * returning undefined for every test after the first -- silently breaking the
 * photo preview and the theme lookup rather than failing loudly.
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

if (!URL.createObjectURL) {
  let counter = 0;
  URL.createObjectURL = () => `blob:test-${++counter}`;
  URL.revokeObjectURL = () => {};
}
