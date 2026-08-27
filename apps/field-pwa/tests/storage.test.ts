import { describe, expect, it, vi } from "vitest";
import { enqueue, listQueue, newId } from "../src/db/queue";
import {
  EVICTION_THRESHOLD,
  WARNING_THRESHOLD,
  ensureRoom,
  estimate,
  evictOriginals,
  formatBytes,
} from "../src/db/storage";
import type { QueuedCapture } from "../src/db/schema";

/**
 * The storage guard.
 *
 * This exists because of a specific trade-off: original camera files are kept
 * until the server confirms receipt, which roughly doubles peak storage on a
 * phone that may have a couple of gigabytes free. Without eviction, a week of
 * bad connectivity fills the device and IndexedDB starts rejecting writes --
 * the worst failure available, because it silently stops the app recording
 * anything at all.
 *
 * The rule under test: originals are expendable, compressed uploads never are.
 */

function withOriginal(createdAt: string): QueuedCapture {
  return {
    id: newId(),
    kind: "capture",
    status: "pending",
    beneficiaryId: "c1",
    beneficiaryName: "कमला",
    awcCode: "A1",
    mealType: "lunch",
    capturedAt: createdAt,
    photoData: new Uint8Array(1024).buffer,
    photoType: "image/jpeg",
    originalData: new Uint8Array(64 * 1024).buffer,
    photoBytes: 1024,
    originalBytes: 64 * 1024,
    attempts: 0,
    createdAt,
  };
}

function mockQuota(ratio: number | null) {
  if (ratio === null) {
    Object.defineProperty(navigator, "storage", { value: undefined, configurable: true });
    return;
  }
  Object.defineProperty(navigator, "storage", {
    value: {
      estimate: vi.fn().mockResolvedValue({ usage: ratio * 1_000_000, quota: 1_000_000 }),
      persist: vi.fn().mockResolvedValue(true),
      persisted: vi.fn().mockResolvedValue(false),
    },
    configurable: true,
  });
}

describe("storage estimate", () => {
  it("reports the usage ratio when the Storage API exists", async () => {
    mockQuota(0.5);
    const result = await estimate();
    expect(result.supported).toBe(true);
    expect(result.ratio).toBeCloseTo(0.5);
  });

  it("degrades gracefully on WebViews without the Storage API", async () => {
    // Older Android WebViews have no navigator.storage. We cannot measure, so
    // we must not pretend to -- and must not block writes either.
    mockQuota(null);
    const result = await estimate();
    expect(result.supported).toBe(false);
    expect(result.ratio).toBeNull();
  });
});

describe("eviction", () => {
  it("drops originals but never the compressed upload", async () => {
    await enqueue(withOriginal("2026-08-01T09:00:00Z"));
    expect(await evictOriginals()).toBe(1);

    const [stored] = (await listQueue()) as QueuedCapture[];
    expect(stored?.originalData).toBeUndefined();
    expect(stored?.originalBytes).toBe(0);
    // The evidence itself survives. If storage were so tight that even this had
    // to go, the right answer would be to stop accepting captures and say so.
    expect(stored?.photoData.byteLength).toBe(1024);
  });

  it("evicts oldest first", async () => {
    await enqueue(withOriginal("2026-08-03T09:00:00Z"));
    await enqueue(withOriginal("2026-08-01T09:00:00Z"));
    await evictOriginals(1);
    const items = (await listQueue()) as QueuedCapture[];
    expect(items[0]?.originalData).toBeUndefined();
    expect(items[1]?.originalData).toBeDefined();
  });

  it("is a no-op when there is nothing left to evict", async () => {
    expect(await evictOriginals()).toBe(0);
  });
});

describe("ensureRoom", () => {
  it("evicts once usage crosses the eviction threshold", async () => {
    await enqueue(withOriginal("2026-08-01T09:00:00Z"));
    mockQuota(EVICTION_THRESHOLD + 0.05);
    const result = await ensureRoom();
    expect(result.evicted).toBe(1);
    expect(result.low).toBe(true);
  });

  it("warns before it evicts", async () => {
    // The worker is told storage is tight while there is still room, rather
    // than after data starts disappearing.
    await enqueue(withOriginal("2026-08-01T09:00:00Z"));
    mockQuota(WARNING_THRESHOLD + 0.02);
    const result = await ensureRoom();
    expect(result.evicted).toBe(0);
    expect(result.low).toBe(true);
  });

  it("leaves originals alone when there is plenty of room", async () => {
    await enqueue(withOriginal("2026-08-01T09:00:00Z"));
    mockQuota(0.2);
    expect(await ensureRoom()).toEqual({ evicted: 0, low: false });
    const [stored] = (await listQueue()) as QueuedCapture[];
    expect(stored?.originalData).toBeDefined();
  });

  it("never blocks a capture on an unmeasurable device", async () => {
    mockQuota(null);
    expect(await ensureRoom()).toEqual({ evicted: 0, low: false });
  });
});

describe("formatBytes", () => {
  it("uses units a worker can read", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(200 * 1024)).toBe("200 KB");
    expect(formatBytes(3.5 * 1024 * 1024)).toBe("3.5 MB");
  });
});
