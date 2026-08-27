import { describe, expect, it } from "vitest";
import {
  cacheBeneficiaries,
  clearAll,
  counts,
  enqueue,
  listBeneficiaries,
  listQueue,
  listSendable,
  newId,
  pruneSynced,
  removeItem,
  updateItem,
} from "../src/db/queue";
import type { QueuedCapture, QueuedGrowth } from "../src/db/schema";

/**
 * The offline queue.
 *
 * Section 7's guarantee lives here: a capture is durable the moment it is
 * taken, independent of any network. Every test below is really asking one
 * question -- can a worker lose their day's work?
 */

function capture(overrides: Partial<QueuedCapture> = {}): QueuedCapture {
  return {
    id: newId(),
    kind: "capture",
    status: "pending",
    beneficiaryId: "child-1",
    beneficiaryName: "कमला",
    awcCode: "TEST-A1",
    mealType: "lunch",
    capturedAt: new Date().toISOString(),
    photoData: new Uint8Array(2048).buffer,
    photoType: "image/jpeg",
    photoBytes: 2048,
    originalBytes: 0,
    attempts: 0,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

function growth(overrides: Partial<QueuedGrowth> = {}): QueuedGrowth {
  return {
    id: newId(),
    kind: "growth",
    status: "pending",
    beneficiaryId: "child-1",
    beneficiaryName: "कमला",
    awcCode: "TEST-A1",
    recordedAt: "2026-08-28",
    heightCm: 88,
    weightKg: 11.2,
    attempts: 0,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("queue", () => {
  it("persists a capture with its photo intact", async () => {
    const item = capture();
    await enqueue(item);
    const [stored] = await listQueue();
    expect(stored?.id).toBe(item.id);
    expect((stored as QueuedCapture).photoData.byteLength).toBe(2048);
  });

  it("stores captures and growth entries together", async () => {
    await enqueue(capture());
    await enqueue(growth());
    expect(await listQueue()).toHaveLength(2);
  });

  it("lists oldest first", async () => {
    // A worker checking the queue wants to see what has been stuck longest.
    await enqueue(capture({ createdAt: "2026-08-28T10:00:00Z", beneficiaryName: "second" }));
    await enqueue(capture({ createdAt: "2026-08-28T09:00:00Z", beneficiaryName: "first" }));
    const items = await listQueue();
    expect(items.map((i) => i.beneficiaryName)).toEqual(["first", "second"]);
  });

  it("counts by status for the visible sync badge", async () => {
    await enqueue(capture({ status: "pending" }));
    await enqueue(capture({ status: "pending" }));
    await enqueue(capture({ status: "synced" }));
    await enqueue(capture({ status: "failed" }));
    const result = await counts();
    expect(result).toMatchObject({ pending: 2, synced: 1, failed: 1, total: 4 });
  });

  it("treats stranded 'syncing' items as sendable", async () => {
    // A tab killed mid-upload leaves this state behind. Left alone the record
    // would sit there forever; the worst case of picking it up is a duplicate
    // attempt, and the worst case of ignoring it is lost evidence.
    await enqueue(capture({ status: "syncing" }));
    expect(await listSendable()).toHaveLength(1);
  });

  it("does not offer already-synced items for sending", async () => {
    await enqueue(capture({ status: "synced" }));
    expect(await listSendable()).toHaveLength(0);
  });

  it("updates an item without losing its photo", async () => {
    const item = capture();
    await enqueue(item);
    await updateItem(item.id, { status: "failed", attempts: 3, lastError: "429" });
    const [stored] = await listQueue();
    expect(stored?.status).toBe("failed");
    expect(stored?.attempts).toBe(3);
    expect((stored as QueuedCapture).photoData.byteLength).toBe(2048);
  });

  it("ignores an update to an item that no longer exists", async () => {
    await expect(updateItem("missing", { status: "synced" })).resolves.toBeUndefined();
  });

  it("removes an item on request", async () => {
    const item = capture();
    await enqueue(item);
    await removeItem(item.id);
    expect(await listQueue()).toHaveLength(0);
  });

  it("prunes old synced items but keeps recent ones", async () => {
    const old = new Date(Date.now() - 48 * 3600_000).toISOString();
    await enqueue(capture({ status: "synced", createdAt: old }));
    await enqueue(capture({ status: "synced" }));
    await enqueue(capture({ status: "pending", createdAt: old }));
    expect(await pruneSynced()).toBe(1);
    expect(await listQueue()).toHaveLength(2);
  });

  it("never prunes unsent work no matter how old", async () => {
    const ancient = new Date(Date.now() - 365 * 24 * 3600_000).toISOString();
    await enqueue(capture({ status: "pending", createdAt: ancient }));
    await enqueue(capture({ status: "failed", createdAt: ancient }));
    await pruneSynced();
    expect(await listQueue()).toHaveLength(2);
  });

  it("generates unique ids", () => {
    const ids = new Set(Array.from({ length: 500 }, () => newId()));
    expect(ids.size).toBe(500);
  });
});

describe("cached beneficiaries", () => {
  const rows = [
    { id: "2", name: "रमेश", awcCode: "A1", dob: "2022-01-01", gender: "M", ageMonths: 40, poshanTrackerId: null },
    { id: "1", name: "कमला", awcCode: "A1", dob: "2021-01-01", gender: "F", ageMonths: 52, poshanTrackerId: null },
  ];

  it("caches the list so photo-to-child matching works offline", async () => {
    await cacheBeneficiaries(rows);
    expect(await listBeneficiaries()).toHaveLength(2);
  });

  it("sorts names with the Hindi collation", async () => {
    // Byte order puts Devanagari names in an order no Hindi reader expects,
    // which matters when scanning a dropdown for a child.
    await cacheBeneficiaries(rows);
    const names = (await listBeneficiaries()).map((c) => c.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, "hi")));
  });

  it("is idempotent across repeated syncs", async () => {
    await cacheBeneficiaries(rows);
    await cacheBeneficiaries(rows);
    expect(await listBeneficiaries()).toHaveLength(2);
  });
});

describe("sign out", () => {
  it("clears every local store", async () => {
    await enqueue(capture());
    await cacheBeneficiaries([
      { id: "1", name: "क", awcCode: "A1", dob: "2022-01-01", gender: "F", ageMonths: 20, poshanTrackerId: null },
    ]);
    await clearAll();
    expect(await listQueue()).toHaveLength(0);
    expect(await listBeneficiaries()).toHaveLength(0);
  });
});
