import { type DBSchema, type IDBPDatabase, openDB } from "idb";

/**
 * The offline store. This is the app's real source of truth.
 *
 * Section 7 is unambiguous: capture must work fully offline, the photo and its
 * metadata are written locally the moment they exist, and no network call ever
 * blocks the worker moving to the next plate. Everything here follows from that
 * -- the server is a place the queue eventually drains to, not somewhere the UI
 * waits on.
 *
 * Deliberately not in the Workbox cache. A service-worker cache can be evicted
 * by the browser under storage pressure; a day of unsent plate photographs must
 * not be. IndexedDB with an explicit quota guard (see storage.ts) gives us
 * control over what gets dropped and when.
 */

export const DB_NAME = "poshannetra";
export const DB_VERSION = 1;

export type QueueStatus = "pending" | "syncing" | "synced" | "failed";
export type QueueKind = "capture" | "growth";

export interface QueuedCapture {
  id: string;
  kind: "capture";
  status: QueueStatus;
  beneficiaryId: string;
  beneficiaryName: string;
  awcCode: string;
  mealType: "breakfast" | "lunch" | "thr";
  capturedAt: string;
  /**
   * Downscaled JPEG bytes, ~150-300 KB. This is what actually gets uploaded.
   *
   * Stored as an ArrayBuffer rather than a Blob deliberately. Blob values in
   * IndexedDB have a patchy history on precisely the older Android WebViews
   * this app targets -- some store them but return them empty after a restart,
   * which would lose a day of evidence in the least detectable way possible.
   * ArrayBuffer is structured-cloned reliably everywhere, and reconstructing a
   * Blob at upload time costs nothing.
   */
  photoData: ArrayBuffer;
  photoType: string;
  /**
   * The camera's original bytes, held until the server confirms receipt.
   * Insurance against a compression bug silently degrading every photograph in
   * a pilot we cannot re-run. Dropped on success, and evicted early under
   * storage pressure -- see storage.ts, which is what keeps this affordable on
   * a phone with 16 GB total.
   */
  originalData?: ArrayBuffer;
  photoBytes: number;
  originalBytes: number;
  attempts: number;
  lastError?: string;
  lastAttemptAt?: string;
  createdAt: string;
  serverId?: string;
}

export interface QueuedGrowth {
  id: string;
  kind: "growth";
  status: QueueStatus;
  beneficiaryId: string;
  beneficiaryName: string;
  awcCode: string;
  recordedAt: string;
  heightCm: number;
  weightKg: number;
  attempts: number;
  lastError?: string;
  lastAttemptAt?: string;
  createdAt: string;
  /** Filled from the server response; the classification is never computed
   *  on the device (master prompt, Section 6.4). */
  classification?: string;
  serverId?: string;
}

export type QueueItem = QueuedCapture | QueuedGrowth;

export interface CachedBeneficiary {
  id: string;
  name: string;
  awcCode: string;
  dob: string;
  gender: string;
  ageMonths: number;
  poshanTrackerId: string | null;
  /** Last growth entry date we know of, for the "not yet measured" list. */
  lastMeasuredAt?: string;
}

export interface CachedAwc {
  awcCode: string;
  nameEn: string;
  nameHi: string;
  district: string;
  districtHi: string;
  block: string;
  blockHi: string;
  centreType: string;
}

export interface MetaRecord {
  key: string;
  value: unknown;
  updatedAt: string;
}

interface PoshanDB extends DBSchema {
  queue: {
    key: string;
    value: QueueItem;
    indexes: { "by-status": QueueStatus; "by-created": string; "by-kind": QueueKind };
  };
  beneficiaries: {
    key: string;
    value: CachedBeneficiary;
    indexes: { "by-name": string };
  };
  awcs: { key: string; value: CachedAwc };
  meta: { key: string; value: MetaRecord };
}

/** Rebuild an uploadable Blob from stored bytes. */
export function toBlob(data: ArrayBuffer, type = "image/jpeg"): Blob {
  return new Blob([data], { type });
}

let dbPromise: Promise<IDBPDatabase<PoshanDB>> | null = null;

export function getDb(): Promise<IDBPDatabase<PoshanDB>> {
  if (!dbPromise) {
    dbPromise = openDB<PoshanDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        const queue = db.createObjectStore("queue", { keyPath: "id" });
        queue.createIndex("by-status", "status");
        queue.createIndex("by-created", "createdAt");
        queue.createIndex("by-kind", "kind");

        const beneficiaries = db.createObjectStore("beneficiaries", { keyPath: "id" });
        beneficiaries.createIndex("by-name", "name");

        db.createObjectStore("awcs", { keyPath: "awcCode" });
        db.createObjectStore("meta", { keyPath: "key" });
      },
    });
  }
  return dbPromise;
}

/**
 * Close the open connection and forget it.
 *
 * IndexedDB will not delete or version-upgrade a database while a connection
 * to it is open -- the request fires `blocked` and waits indefinitely. Anything
 * that needs to tear the database down has to close first, which is why this
 * is a real close rather than just dropping the memoised promise.
 */
export async function closeDb(): Promise<void> {
  if (!dbPromise) return;
  try {
    (await dbPromise).close();
  } catch {
    /* already closed */
  }
  dbPromise = null;
}

/** Test hook: drops the memoised connection so a fresh database is opened. */
export function resetDbForTests(): void {
  dbPromise = null;
}
