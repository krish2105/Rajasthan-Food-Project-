/**
 * Client-side photo downscaling.
 *
 * A modern Android camera produces a 3-6 MB JPEG. Fifty plates a day is 250 MB
 * queued on a phone with 16 GB total, waiting to upload over a rural
 * connection. Downscaling to roughly 1280px turns that into about 12 MB, which
 * is the difference between a queue that drains overnight and one that never
 * does.
 *
 * 1280px is chosen against the consumer, not by taste: Gemini's vision input is
 * tiled at a far lower effective resolution, so a larger image costs upload
 * time and free-tier budget without improving recognition. Section 6.5's
 * portion-estimation target is about how well a model judges volume from a
 * photograph, not about pixel count.
 *
 * The original is retained separately by the caller until the server confirms
 * receipt -- insurance against a bug here silently degrading every photograph
 * in a pilot that cannot be re-run. `src/db/storage.ts` bounds what that costs.
 */

export const MAX_EDGE_PX = 1280;
export const JPEG_QUALITY = 0.7;
/** Anything larger than this after compression is refused rather than queued. */
export const MAX_COMPRESSED_BYTES = 2 * 1024 * 1024;

export interface CompressedPhoto {
  blob: Blob;
  width: number;
  height: number;
  bytes: number;
  originalBytes: number;
  /** True when the source was already small enough to pass through untouched. */
  passthrough: boolean;
}

/**
 * How long to wait for the browser to decode a photograph before giving up.
 *
 * Not defensive padding -- a real failure mode. An <img> is only guaranteed to
 * fire `load` or `error` if the environment actually decodes images, and there
 * are WebView configurations (and, notably, jsdom) where neither ever fires.
 * Without a timeout the promise never settles, the save button spins forever
 * and the worker is stuck on a screen with no way forward while holding a plate.
 *
 * Eight seconds is generous for a local blob on a slow CPU and still short
 * enough that the fallback -- queue the original, uncompressed -- feels like a
 * pause rather than a hang.
 */
export const DECODE_TIMEOUT_MS = 8000;

function loadImage(file: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    let settled = false;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      URL.revokeObjectURL(url);
      fn();
    };

    const timer = window.setTimeout(
      () => finish(() => reject(new Error("image decode timed out"))),
      DECODE_TIMEOUT_MS,
    );

    const img = new Image();
    img.onload = () => finish(() => resolve(img));
    img.onerror = () => finish(() => reject(new Error("could not decode image")));
    img.src = url;
  });
}

export function scaledSize(
  width: number,
  height: number,
  maxEdge = MAX_EDGE_PX,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxEdge) return { width, height };
  const factor = maxEdge / longest;
  return {
    width: Math.max(1, Math.round(width * factor)),
    height: Math.max(1, Math.round(height * factor)),
  };
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("canvas encoding failed"))),
      "image/jpeg",
      quality,
    );
  });
}

/**
 * Downscale and re-encode. Falls back to the original on any failure.
 *
 * The fallback matters more than the optimisation: a decode error on some
 * unusual device must not stop a worker recording a meal. A large queued photo
 * is a storage problem; a lost photo is a lost day.
 */
export async function compressPhoto(
  file: Blob,
  { maxEdge = MAX_EDGE_PX, quality = JPEG_QUALITY } = {},
): Promise<CompressedPhoto> {
  const originalBytes = file.size;

  try {
    const img = await loadImage(file);
    const { width, height } = scaledSize(img.naturalWidth, img.naturalHeight, maxEdge);

    if (width === img.naturalWidth && height === img.naturalHeight && originalBytes < 400_000) {
      return {
        blob: file,
        width,
        height,
        bytes: originalBytes,
        originalBytes,
        passthrough: true,
      };
    }

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2d context");
    ctx.drawImage(img, 0, 0, width, height);

    const blob = await canvasToBlob(canvas, quality);
    // Re-encoding can enlarge an already well-compressed source. Keeping the
    // smaller of the two is free and occasionally saves a lot.
    if (blob.size >= originalBytes) {
      return {
        blob: file,
        width: img.naturalWidth,
        height: img.naturalHeight,
        bytes: originalBytes,
        originalBytes,
        passthrough: true,
      };
    }
    return { blob, width, height, bytes: blob.size, originalBytes, passthrough: false };
  } catch {
    return {
      blob: file,
      width: 0,
      height: 0,
      bytes: originalBytes,
      originalBytes,
      passthrough: true,
    };
  }
}
