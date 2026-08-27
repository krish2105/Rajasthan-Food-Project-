import { describe, expect, it, vi } from "vitest";
import { detectCapability, openStream, stopStream } from "../src/capture/camera";

/**
 * Camera capability detection and, above all, the fallback.
 *
 * The file input is the default and the viewfinder is the upgrade -- so the
 * fallback path is the one that runs on the oldest phones in the pilot, which
 * is exactly the path that normally goes untested. It gets equal coverage here
 * on purpose, and every failure mode is asserted to resolve *towards* it rather
 * than towards an error screen. A worker holding a plate should never meet a
 * dead end.
 */

function setMediaDevices(value: unknown) {
  Object.defineProperty(navigator, "mediaDevices", { value, configurable: true });
}

function setSecureContext(value: boolean) {
  Object.defineProperty(window, "isSecureContext", { value, configurable: true });
}

describe("detectCapability", () => {
  it("chooses the viewfinder when everything is supported", () => {
    setMediaDevices({ getUserMedia: vi.fn() });
    setSecureContext(true);
    expect(detectCapability().mode).toBe("viewfinder");
  });

  it("falls back when getUserMedia is missing", () => {
    setMediaDevices(undefined);
    expect(detectCapability()).toEqual({
      mode: "file-input",
      reason: "getUserMedia unavailable",
    });
  });

  it("falls back when mediaDevices exists but getUserMedia does not", () => {
    setMediaDevices({});
    expect(detectCapability().mode).toBe("file-input");
  });

  it("falls back outside a secure context", () => {
    // On plain HTTP getUserMedia exists but always rejects, which would look
    // like the worker denying permission when they never saw a prompt.
    setMediaDevices({ getUserMedia: vi.fn() });
    setSecureContext(false);
    expect(detectCapability()).toEqual({ mode: "file-input", reason: "insecure context" });
  });
});

describe("openStream", () => {
  it("returns a stream when the camera opens", async () => {
    const stream = { getTracks: () => [] } as unknown as MediaStream;
    setMediaDevices({ getUserMedia: vi.fn().mockResolvedValue(stream) });
    setSecureContext(true);
    const result = await openStream();
    expect(result.stream).toBe(stream);
    expect(result.fallback).toBe(false);
  });

  it("requests the rear camera without demanding it", async () => {
    // `ideal` rather than `exact`: an exact constraint fails outright on
    // cameras that cannot match it, and any camera beats no camera.
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [] });
    setMediaDevices({ getUserMedia });
    setSecureContext(true);
    await openStream();
    const constraints = getUserMedia.mock.calls[0]?.[0];
    expect(constraints.video.facingMode).toEqual({ ideal: "environment" });
    expect(constraints.audio).toBe(false);
  });

  it("falls back when the worker denies permission", async () => {
    const error = new Error("denied");
    error.name = "NotAllowedError";
    setMediaDevices({ getUserMedia: vi.fn().mockRejectedValue(error) });
    setSecureContext(true);
    const result = await openStream();
    expect(result.fallback).toBe(true);
    expect(result.reason).toBe("NotAllowedError");
  });

  it("falls back when no camera exists", async () => {
    const error = new Error("none");
    error.name = "NotFoundError";
    setMediaDevices({ getUserMedia: vi.fn().mockRejectedValue(error) });
    setSecureContext(true);
    expect((await openStream()).fallback).toBe(true);
  });

  it("falls back when another app holds the camera", async () => {
    const error = new Error("busy");
    error.name = "NotReadableError";
    setMediaDevices({ getUserMedia: vi.fn().mockRejectedValue(error) });
    setSecureContext(true);
    expect((await openStream()).fallback).toBe(true);
  });

  it("never rejects, whatever goes wrong", async () => {
    // The capture screen has no catch around this. Every failure has to arrive
    // as a fallback instruction, not as an exception.
    setMediaDevices({ getUserMedia: vi.fn().mockRejectedValue("not even an Error") });
    setSecureContext(true);
    await expect(openStream()).resolves.toMatchObject({ fallback: true });
  });
});

describe("stopStream", () => {
  it("stops every track so the camera light goes out", async () => {
    const stop = vi.fn();
    stopStream({ getTracks: () => [{ stop }, { stop }] } as unknown as MediaStream);
    expect(stop).toHaveBeenCalledTimes(2);
  });

  it("tolerates a null stream", () => {
    expect(() => stopStream(null)).not.toThrow();
  });
});
