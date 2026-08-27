/**
 * Camera capability detection.
 *
 * Two capture paths exist: an in-app viewfinder using getUserMedia, and the
 * phone's own camera app via `<input type="file" capture="environment">`.
 *
 * The file input is the **default**, and the viewfinder is the upgrade. That
 * ordering is deliberate. The viewfinder is nicer and lets us show framing
 * guidance, but it needs a camera permission, a live video stream and a
 * canvas grab -- three things that fail in different ways across the older
 * Android WebViews this app targets, and that cost CPU on a device with little
 * to spare. The file input opens the camera the worker already knows, with
 * their flash and focus controls, and works essentially everywhere.
 *
 * So every failure here resolves *towards* the fallback rather than towards an
 * error screen, and the fallback path is exercised by the test suite as
 * thoroughly as the viewfinder -- it is the path that runs on the devices that
 * need it most, which is exactly the path that usually goes untested.
 */

export type CaptureMode = "viewfinder" | "file-input";

export interface CameraCapability {
  mode: CaptureMode;
  reason: string;
}

export function detectCapability(): CameraCapability {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { mode: "file-input", reason: "getUserMedia unavailable" };
  }
  if (typeof document === "undefined" || !document.createElement("canvas").getContext) {
    return { mode: "file-input", reason: "canvas unavailable" };
  }
  // getUserMedia is gated on a secure context; on plain HTTP it exists but
  // always rejects, which would look like a permission denial to the worker.
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return { mode: "file-input", reason: "insecure context" };
  }
  return { mode: "viewfinder", reason: "supported" };
}

export interface StreamResult {
  stream: MediaStream | null;
  fallback: boolean;
  reason?: string;
}

/** Opens the rear camera, degrading to the file input on any failure. */
export async function openStream(): Promise<StreamResult> {
  const capability = detectCapability();
  if (capability.mode === "file-input") {
    return { stream: null, fallback: true, reason: capability.reason };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        // Requested, not required: an exact constraint fails outright on
        // cameras that cannot match it, and a lower resolution is fine since
        // the image is downscaled to 1280px anyway.
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
    return { stream, fallback: false };
  } catch (error) {
    const reason = error instanceof Error ? error.name : "unknown";
    return { stream: null, fallback: true, reason };
  }
}

export function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

/** Grabs a still from a live video element. */
export function grabFrame(video: HTMLVideoElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) {
      reject(new Error("video not ready"));
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      reject(new Error("no 2d context"));
      return;
    }
    ctx.drawImage(video, 0, 0, width, height);
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("frame encoding failed"))),
      "image/jpeg",
      // Grabbed at high quality; compressPhoto does the real reduction, so a
      // lossy grab here would compound with that one.
      0.92,
    );
  });
}
