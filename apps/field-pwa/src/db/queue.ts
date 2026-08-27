import { getDb } from "./schema";
import type { CachedAwc, CachedBeneficiary, QueueItem, QueueStatus } from "./schema";

/**
 * Queue operations.
 *
 * Everything a worker does is written here first and synced later. The
 * important guarantee is in `enqueue`: it returns once the record is durably
 * in IndexedDB, and nothing about the network is consulted. Section 7's rule
 * is that no network call blocks the capture flow, and the cleanest way to
 * honour it is for the capture path to have no idea whether a network exists.
 */

export function newId(): string {
  // randomUUID is missing on the older Android WebViews this app targets, so
  // there is a fallback rather than a crash on the first capture.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 11)}`;
}

export async function enqueue(item: QueueItem): Promise<void> {
  const db = await getDb();
  await db.put("queue", item);
}

export async function getItem(id: string): Promise<QueueItem | undefined> {
  const db = await getDb();
  return db.get("queue", id);
}

export async function updateItem(id: string, patch: Partial<QueueItem>): Promise<void> {
  const db = await getDb();
  const existing = await db.get("queue", id);
  if (!existing) return;
  await db.put("queue", { ...existing, ...patch } as QueueItem);
}

export async function removeItem(id: string): Promise<void> {
  const db = await getDb();
  await db.delete("queue", id);
}

export async function listQueue(): Promise<QueueItem[]> {
  const db = await getDb();
  const all = await db.getAll("queue");
  // Oldest first: a worker looking at the queue wants to see what has been
  // stuck longest, not what they did a moment ago.
  return all.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export async function listByStatus(status: QueueStatus): Promise<QueueItem[]> {
  const db = await getDb();
  return db.getAllFromIndex("queue", "by-status", status);
}

/**
 * Items eligible for a sync attempt.
 *
 * `syncing` is included because it is a lie after a crash: the tab can be
 * killed mid-upload and leave a record stranded in that state forever. Picking
 * them back up costs at worst a duplicate attempt; leaving them costs the
 * worker their day's work.
 */
export async function listSendable(): Promise<QueueItem[]> {
  const [pending, failed, stuck] = await Promise.all([
    listByStatus("pending"),
    listByStatus("failed"),
    listByStatus("syncing"),
  ]);
  return [...pending, ...failed, ...stuck].sort((a, b) =>
    a.createdAt.localeCompare(b.createdAt),
  );
}

export interface QueueCounts {
  pending: number;
  syncing: number;
  synced: number;
  failed: number;
  total: number;
}

/**
 * Counts for the status badge.
 *
 * Section 7 asks for sync status to be visible rather than silent -- "12
 * pending, 3 synced" so a worker is never left wondering whether the day was
 * recorded. This feeds that, and it is polled cheaply rather than pushed.
 */
export async function counts(): Promise<QueueCounts> {
  const items = await listQueue();
  const result: QueueCounts = { pending: 0, syncing: 0, synced: 0, failed: 0, total: items.length };
  for (const item of items) result[item.status] += 1;
  return result;
}

/** Successfully sent items, kept briefly so "sent" is visible, then cleared. */
export async function pruneSynced(keepMs = 24 * 60 * 60 * 1000): Promise<number> {
  const db = await getDb();
  const synced = await db.getAllFromIndex("queue", "by-status", "synced");
  const cutoff = Date.now() - keepMs;
  let removed = 0;
  for (const item of synced) {
    if (new Date(item.createdAt).getTime() < cutoff) {
      await db.delete("queue", item.id);
      removed += 1;
    }
  }
  return removed;
}

// --- Cached reference data ------------------------------------------------
// Section 7: the beneficiary list is cached on first sign-in so matching a
// photo to a child works offline. A live search would strand the worker.

export async function cacheBeneficiaries(rows: CachedBeneficiary[]): Promise<void> {
  const db = await getDb();
  const tx = db.transaction("beneficiaries", "readwrite");
  await Promise.all(rows.map((row) => tx.store.put(row)));
  await tx.done;
  await setMeta("beneficiariesUpdatedAt", new Date().toISOString());
}

export async function listBeneficiaries(): Promise<CachedBeneficiary[]> {
  const db = await getDb();
  const all = await db.getAll("beneficiaries");
  // Devanagari sorts correctly under the hi locale; the default byte order
  // does not, and a worker scanning for a name would find it in the wrong place.
  return all.sort((a, b) => a.name.localeCompare(b.name, "hi"));
}

export async function cacheAwcs(rows: CachedAwc[]): Promise<void> {
  const db = await getDb();
  const tx = db.transaction("awcs", "readwrite");
  await Promise.all(rows.map((row) => tx.store.put(row)));
  await tx.done;
}

export async function listAwcs(): Promise<CachedAwc[]> {
  const db = await getDb();
  return db.getAll("awcs");
}

export async function setMeta(key: string, value: unknown): Promise<void> {
  const db = await getDb();
  await db.put("meta", { key, value, updatedAt: new Date().toISOString() });
}

export async function getMeta<T>(key: string): Promise<T | undefined> {
  const db = await getDb();
  const record = await db.get("meta", key);
  return record?.value as T | undefined;
}

/** Sign-out: clears everything. Guarded in the UI when the queue is not empty. */
export async function clearAll(): Promise<void> {
  const db = await getDb();
  await Promise.all([
    db.clear("queue"),
    db.clear("beneficiaries"),
    db.clear("awcs"),
    db.clear("meta"),
  ]);
}
