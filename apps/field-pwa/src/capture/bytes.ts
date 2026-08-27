/**
 * Read a Blob's bytes, with a fallback for environments that lack
 * `Blob.prototype.arrayBuffer`.
 *
 * That method arrived in Chrome and Android WebView 76 (2019). Most phones in
 * the pilot will have it, but "most" is not the bar: on a device that does not,
 * calling it directly throws a TypeError inside the save handler, the worker
 * sees a generic "something went wrong", and the meal goes unrecorded with no
 * indication of why. FileReader has been available since forever and costs a
 * few lines.
 *
 * Found by testing -- jsdom has the same gap, which is what surfaced it.
 */
export function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") {
    return blob.arrayBuffer();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (result instanceof ArrayBuffer) resolve(result);
      else reject(new Error("unexpected FileReader result"));
    };
    reader.onerror = () => reject(reader.error ?? new Error("could not read photo"));
    reader.readAsArrayBuffer(blob);
  });
}
