import { describe, expect, it, vi } from "vitest";
import { blobToArrayBuffer } from "../src/capture/bytes";
import { DECODE_TIMEOUT_MS, MAX_EDGE_PX, compressPhoto, scaledSize } from "../src/capture/compress";

/**
 * Photo downscaling.
 *
 * jsdom has no canvas, so `compressPhoto` takes its own fallback path here --
 * which is itself the most important thing to verify. A decode failure on some
 * unusual device must return the original photograph, never nothing. A large
 * queued photo is a storage problem; a lost photo is a lost meal record.
 */

describe("scaledSize", () => {
  it("leaves images already within the limit alone", () => {
    expect(scaledSize(800, 600)).toEqual({ width: 800, height: 600 });
  });

  it("scales the long edge down to the limit", () => {
    expect(scaledSize(4000, 3000)).toEqual({ width: 1280, height: 960 });
  });

  it("handles portrait orientation", () => {
    // Phones are held vertically; getting this backwards would crop nothing and
    // scale nothing on the most common input.
    expect(scaledSize(3000, 4000)).toEqual({ width: 960, height: 1280 });
  });

  it("preserves aspect ratio", () => {
    const { width, height } = scaledSize(4032, 3024);
    expect(width / height).toBeCloseTo(4032 / 3024, 3);
  });

  it("never produces a zero dimension", () => {
    const { width, height } = scaledSize(10000, 3, MAX_EDGE_PX);
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThan(0);
  });
});

describe("compressPhoto", () => {
  // jsdom never fires load or error on an <img>, which is exactly the hang the
  // decode timeout exists to break. Fake timers let us reach it instantly.
  const withFakeTimers = async <T,>(run: () => Promise<T>): Promise<T> => {
    vi.useFakeTimers();
    const promise = run();
    await vi.advanceTimersByTimeAsync(DECODE_TIMEOUT_MS + 100);
    const result = await promise;
    vi.useRealTimers();
    return result;
  };

  it("gives up decoding rather than hanging forever", async () => {
    // The bug this pins: without a timeout the promise never settles, the save
    // button spins indefinitely, and the worker cannot record the meal.
    const blob = new Blob([new Uint8Array(1024)], { type: "image/jpeg" });
    const result = await withFakeTimers(() => compressPhoto(blob));
    expect(result.blob).toBe(blob);
    expect(result.passthrough).toBe(true);
  });

  it("returns the original when the image cannot be decoded", async () => {
    const blob = new Blob([new Uint8Array(1024)], { type: "image/jpeg" });
    const result = await withFakeTimers(() => compressPhoto(blob));
    expect(result.blob).toBe(blob);
    expect(result.passthrough).toBe(true);
    expect(result.bytes).toBe(1024);
  });

  it("always reports the original byte count", async () => {
    // The queue uses this to decide what to evict under storage pressure.
    const blob = new Blob([new Uint8Array(4 * 1024 * 1024)], { type: "image/jpeg" });
    const result = await withFakeTimers(() => compressPhoto(blob));
    expect(result.originalBytes).toBe(4 * 1024 * 1024);
  });

  it("never rejects", async () => {
    // The capture path has no error branch for this by design.
    await expect(withFakeTimers(() => compressPhoto(new Blob([])))).resolves.toBeDefined();
  });
});

describe("blobToArrayBuffer", () => {
  it("reads bytes where Blob.arrayBuffer is missing", async () => {
    // Android WebView only gained Blob.arrayBuffer in version 76. Without the
    // FileReader fallback, saving a capture on an older device throws inside
    // the handler and the worker sees a generic error with no way forward.
    const blob = new Blob([new Uint8Array([1, 2, 3, 4])]);
    expect(typeof blob.arrayBuffer).toBe("undefined");
    const buffer = await blobToArrayBuffer(blob);
    expect(new Uint8Array(buffer)).toEqual(new Uint8Array([1, 2, 3, 4]));
  });

  it("uses the native method when it exists", async () => {
    const native = vi.fn().mockResolvedValue(new Uint8Array([9]).buffer);
    const blob = Object.assign(new Blob([new Uint8Array([9])]), { arrayBuffer: native });
    await blobToArrayBuffer(blob);
    expect(native).toHaveBeenCalled();
  });
});
