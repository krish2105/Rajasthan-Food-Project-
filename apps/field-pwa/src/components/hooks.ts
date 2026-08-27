import { useCallback, useEffect, useState } from "react";
import { counts as queueCounts } from "../db/queue";
import type { QueueCounts } from "../db/queue";

/**
 * Connectivity state.
 *
 * `navigator.onLine` is famously optimistic: Android reports online the moment
 * it associates with a wifi access point, well before a route to the internet
 * exists. It is still the right signal to *display*, because it matches what
 * the phone's own status bar shows the worker, and a banner that disagreed with
 * their signal bars would read as a bug in the app.
 *
 * The sync engine does not trust it -- it just tries, and treats the failure as
 * data. Display and behaviour are allowed to differ here.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return online;
}

const EMPTY: QueueCounts = { pending: 0, syncing: 0, synced: 0, failed: 0, total: 0 };

/**
 * Live queue counts for the "12 waiting, 3 sent" badge Section 7 asks for.
 *
 * Polled rather than pushed. An event bus over IndexedDB writes would be
 * tidier, but the counts change from several places (capture, growth, sync,
 * eviction) and a missed event shows the worker a stale number for their day's
 * work -- the one thing this display exists to prevent. A cheap query every few
 * seconds cannot go stale.
 */
export function useQueueCounts(intervalMs = 3000): { counts: QueueCounts; refresh: () => void } {
  const [counts, setCounts] = useState<QueueCounts>(EMPTY);

  const refresh = useCallback(() => {
    void queueCounts().then(setCounts).catch(() => setCounts(EMPTY));
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, intervalMs);
    return () => window.clearInterval(timer);
  }, [refresh, intervalMs]);

  return { counts, refresh };
}

/** Announces a message to screen readers without stealing focus. */
export function useAnnounce(): (message: string) => void {
  return useCallback((message: string) => {
    const region = document.getElementById("live-region");
    if (region) {
      // Cleared first: setting the same text twice in a row is otherwise
      // ignored by most screen readers, so a repeated "Saved" goes unspoken.
      region.textContent = "";
      window.setTimeout(() => {
        region.textContent = message;
      }, 60);
    }
  }, []);
}
