import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MockInstance } from "vitest";
import * as api from "../src/api/client";
import { enqueue, listQueue, newId } from "../src/db/queue";
import { MAX_AUTO_ATTEMPTS, sync } from "../src/sync/engine";
import type { QueuedCapture, QueuedGrowth } from "../src/db/schema";

/**
 * The sync engine.
 *
 * Section 7 requires the pipeline to be retry-safe and never capture-blocking.
 * The tests below are all variations on one question: after this failure, is
 * the worker's evidence still on the phone and still sendable?
 */

function capture(overrides: Partial<QueuedCapture> = {}): QueuedCapture {
  return {
    id: newId(),
    kind: "capture",
    status: "pending",
    beneficiaryId: "child-1",
    beneficiaryName: "कमला",
    awcCode: "A1",
    mealType: "lunch",
    capturedAt: "2026-08-28T06:00:00Z",
    photoData: new Uint8Array(512).buffer,
    photoType: "image/jpeg",
    originalData: new Uint8Array(4096).buffer,
    photoBytes: 512,
    originalBytes: 4096,
    attempts: 0,
    createdAt: "2026-08-28T06:00:00Z",
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
    awcCode: "A1",
    recordedAt: "2026-08-28",
    heightCm: 88,
    weightKg: 11.2,
    attempts: 0,
    createdAt: "2026-08-28T06:00:00Z",
    ...overrides,
  };
}

// Typed against the real signatures so a change to the API client surfaces
// here rather than as a runtime surprise during a sync.
let uploadSpy: MockInstance<typeof api.uploadCapture>;

beforeEach(() => {
  uploadSpy = vi.spyOn(api, "uploadCapture").mockResolvedValue({ id: "srv-1" });
  vi.spyOn(api, "recordGrowth").mockResolvedValue({
    entry: {
      id: "srv-g1",
      classification: "MAM",
      standard_used: "who_2006_0_60m",
      waz_score: -2.1,
      haz_score: -1.8,
      whz_score: -2.4,
      baz_score: null,
      data_quality_flags: [],
    },
    notes: [],
  });
});

afterEach(() => vi.restoreAllMocks());

describe("successful sync", () => {
  it("uploads a capture and marks it sent", async () => {
    await enqueue(capture());
    const outcome = await sync({ force: true });
    expect(outcome.sent).toBe(1);
    const [stored] = await listQueue();
    expect(stored?.status).toBe("synced");
    expect(stored?.serverId).toBe("srv-1");
  });

  it("frees the original once the server has the photo", async () => {
    // The insurance has paid out; the space goes back to the worker's phone.
    await enqueue(capture());
    await sync({ force: true });
    const [stored] = (await listQueue()) as QueuedCapture[];
    expect(stored?.originalData).toBeUndefined();
    expect(stored?.originalBytes).toBe(0);
    expect(stored?.photoData.byteLength).toBe(512);
  });

  it("stores the classification the server computed for a growth entry", async () => {
    // Section 6.4: the status is never computed on the device.
    await enqueue(growth());
    await sync({ force: true });
    const [stored] = (await listQueue()) as QueuedGrowth[];
    expect(stored?.classification).toBe("MAM");
  });

  it("sends serially, not in parallel", async () => {
    // Ten concurrent multipart uploads over a 2G link is slower end-to-end
    // than one, and makes the progress display meaningless.
    let concurrent = 0;
    let peak = 0;
    uploadSpy.mockImplementation(async () => {
      concurrent += 1;
      peak = Math.max(peak, concurrent);
      await new Promise((r) => setTimeout(r, 5));
      concurrent -= 1;
      return { id: "srv" };
    });
    await Promise.all([enqueue(capture()), enqueue(capture()), enqueue(capture())]);
    await sync({ force: true });
    expect(peak).toBe(1);
  });

  it("reports progress so the worker can decide whether to wait", async () => {
    await enqueue(capture());
    await enqueue(capture());
    const seen: number[] = [];
    await sync({ force: true, onProgress: (p) => seen.push(p.done) });
    expect(seen.at(-1)).toBe(2);
  });
});

describe("failure handling", () => {
  it("keeps the photo when the upload fails", async () => {
    // The single most important property in this file.
    uploadSpy.mockRejectedValue(new api.ApiError("network unavailable", 0));
    await enqueue(capture());
    await sync({ force: true });
    const [stored] = (await listQueue()) as QueuedCapture[];
    expect(stored?.status).toBe("failed");
    expect(stored?.photoData.byteLength).toBe(512);
    expect(stored?.lastError).toContain("network");
  });

  it("counts attempts so backoff survives the app being killed", async () => {
    uploadSpy.mockRejectedValue(new api.ApiError("boom", 500));
    await enqueue(capture());
    await sync({ force: true });
    await sync({ force: true });
    const [stored] = await listQueue();
    expect(stored?.attempts).toBe(2);
  });

  it("stops the whole run on an auth failure instead of burning attempts", async () => {
    // Every remaining item would fail identically; the fix is a sign-in, not
    // five more uploads each.
    uploadSpy.mockRejectedValue(new api.ApiError("token expired", 401));
    await enqueue(capture());
    await enqueue(capture());
    const outcome = await sync({ force: true });
    expect(outcome.authFailure).toBe(true);
    expect(uploadSpy).toHaveBeenCalledTimes(1);
  });

  it("does not increment attempts on an auth failure", async () => {
    uploadSpy.mockRejectedValue(new api.ApiError("token expired", 401));
    await enqueue(capture());
    await sync({ force: true });
    const [stored] = await listQueue();
    expect(stored?.attempts).toBe(0);
  });

  it("carries on past one failure to reach the rest", async () => {
    uploadSpy
      .mockRejectedValueOnce(new api.ApiError("boom", 500))
      .mockResolvedValue({ id: "srv" });
    await enqueue(capture({ createdAt: "2026-08-28T06:00:00Z" }));
    await enqueue(capture({ createdAt: "2026-08-28T07:00:00Z" }));
    const outcome = await sync({ force: true });
    expect(outcome.failed).toBe(1);
    expect(outcome.sent).toBe(1);
  });

  it("does not retry an item that has exhausted its automatic attempts", async () => {
    // It waits for a human instead of retrying forever on a flat battery.
    await enqueue(capture({ status: "failed", attempts: MAX_AUTO_ATTEMPTS, lastAttemptAt: new Date().toISOString() }));
    const outcome = await sync();
    expect(outcome.skipped).toBe(1);
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("still retries an exhausted item when the worker asks", async () => {
    await enqueue(capture({ status: "failed", attempts: MAX_AUTO_ATTEMPTS, lastAttemptAt: new Date().toISOString() }));
    await sync({ force: true });
    expect(uploadSpy).toHaveBeenCalledTimes(1);
  });
});

describe("backoff", () => {
  it("waits before retrying a recent failure", async () => {
    await enqueue(capture({ status: "failed", attempts: 2, lastAttemptAt: new Date().toISOString() }));
    const outcome = await sync();
    expect(outcome.skipped).toBe(1);
  });

  it("retries once the backoff window has passed", async () => {
    const long_ago = new Date(Date.now() - 3 * 3600_000).toISOString();
    await enqueue(capture({ status: "failed", attempts: 2, lastAttemptAt: long_ago }));
    await sync();
    expect(uploadSpy).toHaveBeenCalledTimes(1);
  });

  it("always tries an item that has never been attempted", async () => {
    await enqueue(capture({ attempts: 0 }));
    await sync();
    expect(uploadSpy).toHaveBeenCalledTimes(1);
  });
});

describe("re-entrancy", () => {
  it("ignores a second run while one is in flight", async () => {
    // A manual tap during an automatic run must not double-upload.
    uploadSpy.mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 20));
      return { id: "srv" };
    });
    await enqueue(capture());
    const [first, second] = await Promise.all([sync({ force: true }), sync({ force: true })]);
    expect(first.sent + second.sent).toBe(1);
    expect(uploadSpy).toHaveBeenCalledTimes(1);
  });
});

describe("ApiError classification", () => {
  it("treats a network failure as retryable", () => {
    expect(new api.ApiError("offline", 0).retryable).toBe(true);
  });

  it("treats server errors and rate limits as retryable", () => {
    expect(new api.ApiError("boom", 500).retryable).toBe(true);
    expect(new api.ApiError("slow down", 429).retryable).toBe(true);
  });

  it("does not retry a request that is simply wrong", () => {
    // Retrying a malformed capture forever burns battery and hides the fault.
    expect(new api.ApiError("bad", 422).retryable).toBe(false);
    expect(new api.ApiError("nope", 404).retryable).toBe(false);
  });

  it("identifies auth failures separately", () => {
    expect(new api.ApiError("expired", 401).isAuthFailure).toBe(true);
    expect(new api.ApiError("forbidden", 403).isAuthFailure).toBe(true);
    expect(new api.ApiError("boom", 500).isAuthFailure).toBe(false);
  });
});
