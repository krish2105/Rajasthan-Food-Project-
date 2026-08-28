import * as api from "../api/client";
import { listSendable, pruneSynced, updateItem } from "../db/queue";
import { toBlob } from "../db/schema";
import type { QueueItem, QueuedCapture, QueuedGrowth } from "../db/schema";

/**
 * The sync engine.
 *
 * Section 7 asks for background sync "with a manual 'sync now' fallback button
 * since Background Sync isn't reliable on all Android WebViews". That caveat is
 * the design brief: this engine assumes it will be triggered by whichever of
 * several unreliable mechanisms happens to fire first, and must behave
 * correctly if two fire at once or none do.
 *
 * Hence three properties:
 *
 *   - **Serial, not parallel.** One item at a time. Ten concurrent multipart
 *     uploads over a 2G link is slower end-to-end than one, and it makes the
 *     progress display meaningless to a worker trying to decide whether to
 *     wait.
 *   - **Re-entrancy guarded.** A manual tap during an automatic run must not
 *     start a second pass over the same records.
 *   - **Attempt counts persist.** Backoff survives the app being killed, which
 *     on a low-memory Android happens constantly.
 */

/** Beyond this many failures an item stops auto-retrying and waits for a human. */
export const MAX_AUTO_ATTEMPTS = 5;

/** Backoff by attempt number, in minutes. Long tail: a rate limit or an outage
 *  is not fixed by asking again in ten seconds. */
const BACKOFF_MINUTES = [0, 1, 5, 15, 60];

export interface SyncProgress {
  total: number;
  done: number;
  sent: number;
  failed: number;
  current?: string;
}

export interface SyncOutcome {
  sent: number;
  failed: number;
  skipped: number;
  authFailure: boolean;
}

let running = false;

export function isRunning(): boolean {
  return running;
}

function dueForRetry(item: QueueItem, now: number): boolean {
  if (item.status === "synced") return false;
  if (item.attempts === 0 || !item.lastAttemptAt) return true;
  if (item.attempts >= MAX_AUTO_ATTEMPTS) return false;
  const waitMinutes = BACKOFF_MINUTES[Math.min(item.attempts, BACKOFF_MINUTES.length - 1)] ?? 60;
  return now - new Date(item.lastAttemptAt).getTime() >= waitMinutes * 60_000;
}

async function sendCapture(item: QueuedCapture): Promise<string> {
  const result = await api.uploadCapture({
    beneficiaryId: item.beneficiaryId,
    mealType: item.mealType,
    capturedAt: item.capturedAt,
    photo: toBlob(item.photoData, item.photoType),
  });
  return result.id;
}

async function sendGrowth(item: QueuedGrowth): Promise<{ id: string; classification: string }> {
  const result = await api.recordGrowth({
    beneficiaryId: item.beneficiaryId,
    recordedAt: item.recordedAt,
    heightCm: item.heightCm,
    weightKg: item.weightKg,
  });
  return { id: result.entry.id, classification: result.entry.classification };
}

/**
 * Drain the queue.
 *
 * `force` ignores backoff -- it is what the manual "send now" button uses,
 * because a worker who can see they have signal should not be told to wait an
 * hour for a timer they cannot see.
 */
export async function sync(
  options: { force?: boolean; onProgress?: (p: SyncProgress) => void } = {},
): Promise<SyncOutcome> {
  if (running) return { sent: 0, failed: 0, skipped: 0, authFailure: false };
  running = true;

  const outcome: SyncOutcome = { sent: 0, failed: 0, skipped: 0, authFailure: false };
  // One refresh attempt per run. A refresh that fails will fail for every item,
  // and hammering it once per queued photograph would turn one bad token into
  // dozens of requests over a connection that is already poor.
  let refreshed = false;
  try {
    const now = Date.now();
    const all = await listSendable();
    const due = options.force ? all : all.filter((item) => dueForRetry(item, now));
    outcome.skipped = all.length - due.length;

    const progress: SyncProgress = { total: due.length, done: 0, sent: 0, failed: 0 };
    options.onProgress?.(progress);

    for (const item of due) {
      progress.current = item.beneficiaryName;
      options.onProgress?.({ ...progress });

      await updateItem(item.id, { status: "syncing" } as Partial<QueueItem>);
      const attempts = item.attempts + 1;

      try {
        if (item.kind === "capture") {
          const serverId = await sendCapture(item);
          await updateItem(item.id, {
            status: "synced",
            serverId,
            attempts,
            lastAttemptAt: new Date().toISOString(),
            lastError: undefined,
            // The original was insurance against a compression bug. The server
            // has the compressed image now, so the insurance has paid out and
            // the space goes back to the worker's phone.
            originalData: undefined,
            originalBytes: 0,
          } as Partial<QueuedCapture>);
        } else {
          const { id, classification } = await sendGrowth(item);
          await updateItem(item.id, {
            status: "synced",
            serverId: id,
            classification,
            attempts,
            lastAttemptAt: new Date().toISOString(),
            lastError: undefined,
          } as Partial<QueuedGrowth>);
        }
        outcome.sent += 1;
        progress.sent += 1;
      } catch (error) {
        const apiError = error instanceof api.ApiError ? error : null;

        if (apiError?.isAuthFailure) {
          // The access token expired. That is the normal state of affairs on
          // this device, not an emergency: Section 11 makes it one hour long
          // and Section 7 expects days without a connection, so it will have
          // lapsed almost every time a worker regains signal.
          //
          // Try the refresh token before giving up. Only if that also fails
          // has the worker genuinely been signed out -- and even then the queue
          // is untouched, so nothing is lost by asking them to sign in again.
          if (!refreshed) {
            refreshed = true;
            if (await api.refreshSession()) {
              // Put the item back and let the next pass retry it with the new
              // token. Its attempt count is not incremented: an expired token
              // is not the item's fault.
              await updateItem(item.id, {
                status: "pending",
                attempts: item.attempts,
              } as Partial<QueueItem>);
              continue;
            }
          }

          await updateItem(item.id, {
            status: "failed",
            attempts: item.attempts,
            lastError: apiError.message,
          } as Partial<QueueItem>);
          outcome.authFailure = true;
          break;
        }

        await updateItem(item.id, {
          status: "failed",
          attempts,
          lastAttemptAt: new Date().toISOString(),
          lastError: apiError ? apiError.message : String(error),
        } as Partial<QueueItem>);
        outcome.failed += 1;
        progress.failed += 1;
      }

      progress.done += 1;
      options.onProgress?.({ ...progress });
    }

    await pruneSynced();
    return outcome;
  } finally {
    running = false;
  }
}

/**
 * Wire up automatic sync.
 *
 * Three triggers, because none of them is dependable on its own:
 *
 *   - `online` fires when connectivity returns, but Android reports it
 *     optimistically and often before a route actually exists;
 *   - `visibilitychange` catches the worker reopening the app, which in
 *     practice is the most reliable signal of all;
 *   - a slow interval covers the case where the app is left open on a
 *     windowsill and the signal comes back quietly.
 *
 * Section 7's manual button is separate and always available, because all three
 * of these can fail silently and a worker needs a way to make something happen.
 */
export function startAutoSync(
  onOutcome?: (outcome: SyncOutcome) => void,
  intervalMs = 5 * 60_000,
): () => void {
  const run = () => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) return;
    void sync().then((outcome) => {
      if (outcome.sent || outcome.failed || outcome.authFailure) onOutcome?.(outcome);
    });
  };

  const onVisible = () => {
    if (document.visibilityState === "visible") run();
  };

  window.addEventListener("online", run);
  document.addEventListener("visibilitychange", onVisible);
  const timer = window.setInterval(run, intervalMs);

  return () => {
    window.removeEventListener("online", run);
    document.removeEventListener("visibilitychange", onVisible);
    window.clearInterval(timer);
  };
}
