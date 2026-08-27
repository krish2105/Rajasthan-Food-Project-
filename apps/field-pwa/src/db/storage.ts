import { getDb } from "./schema";
import type { QueuedCapture } from "./schema";

/**
 * Storage quota guard.
 *
 * This exists because of a specific decision: original camera files are kept
 * alongside the compressed upload until the server confirms receipt, as
 * insurance against a compression bug silently degrading every photograph in a
 * pilot that cannot be re-run.
 *
 * That insurance roughly doubles peak storage on the device least able to
 * afford it -- a budget Android with 16 GB total, most of it already spoken
 * for. Without a guard, a week of poor connectivity fills the phone and
 * IndexedDB starts throwing QuotaExceededError on write. That failure mode is
 * the worst one available: it silently stops the app recording anything.
 *
 * So the originals are treated as what they are -- a nice-to-have. Under
 * pressure they are evicted, oldest first, and the compressed uploads (the
 * actual evidence) are never touched. The worker is told, in their own
 * language, before it becomes a problem.
 */

/** Below this share of quota remaining, start shedding originals. */
export const EVICTION_THRESHOLD = 0.8;
/** Below this, warn the worker in the UI. */
export const WARNING_THRESHOLD = 0.7;

export interface StorageEstimate {
  usageBytes: number;
  quotaBytes: number;
  /** 0-1. Null when the browser does not implement the Storage API. */
  ratio: number | null;
  supported: boolean;
}

export async function estimate(): Promise<StorageEstimate> {
  if (
    typeof navigator === "undefined" ||
    !navigator.storage ||
    typeof navigator.storage.estimate !== "function"
  ) {
    // Older Android WebViews have no Storage API. We cannot measure, so we
    // fall back to evicting on write failure rather than pre-emptively.
    return { usageBytes: 0, quotaBytes: 0, ratio: null, supported: false };
  }
  const { usage = 0, quota = 0 } = await navigator.storage.estimate();
  return {
    usageBytes: usage,
    quotaBytes: quota,
    ratio: quota > 0 ? usage / quota : null,
    supported: true,
  };
}

export async function isLow(): Promise<boolean> {
  const { ratio } = await estimate();
  return ratio !== null && ratio >= WARNING_THRESHOLD;
}

/**
 * Drop original camera files from the oldest unsent captures.
 *
 * Only `originalData` is removed. The compressed `photoData` is the record of
 * what the child was served and is never evicted -- if storage were tight
 * enough that even those had to go, the right answer would be to stop
 * accepting new captures and say so, not to quietly discard evidence.
 */
export async function evictOriginals(maxToEvict = 50): Promise<number> {
  const db = await getDb();
  const items = await db.getAll("queue");
  const candidates = items
    .filter(
      (item): item is QueuedCapture =>
        item.kind === "capture" && item.originalData !== undefined,
    )
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  let evicted = 0;
  for (const item of candidates.slice(0, maxToEvict)) {
    const { originalData: _dropped, ...rest } = item;
    await db.put("queue", { ...rest, originalBytes: 0 } as QueuedCapture);
    evicted += 1;
  }
  return evicted;
}

/** Called before a capture is written; sheds originals if space is tight. */
export async function ensureRoom(): Promise<{ evicted: number; low: boolean }> {
  const { ratio } = await estimate();
  if (ratio === null) return { evicted: 0, low: false };
  if (ratio >= EVICTION_THRESHOLD) {
    const evicted = await evictOriginals();
    return { evicted, low: true };
  }
  return { evicted: 0, low: ratio >= WARNING_THRESHOLD };
}

/**
 * Ask the browser not to evict us.
 *
 * Best-effort and frequently refused, but on Chrome for Android an installed
 * PWA is usually granted it. Without persistence the browser may clear
 * IndexedDB under pressure, which would take a day of unsent captures with it.
 */
export async function requestPersistence(): Promise<boolean> {
  if (
    typeof navigator === "undefined" ||
    !navigator.storage ||
    typeof navigator.storage.persist !== "function"
  ) {
    return false;
  }
  try {
    if (await navigator.storage.persisted()) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
