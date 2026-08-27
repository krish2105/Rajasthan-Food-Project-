import { useCallback, useEffect, useState } from "react";
import { useAnnounce, useOnline } from "../components/hooks";
import { AlertIcon, CheckIcon, ClockIcon, OfflineIcon, SyncIcon, TrashIcon } from "../components/Icon";
import { listQueue, removeItem, updateItem } from "../db/queue";
import { formatBytes } from "../db/storage";
import type { QueueItem } from "../db/schema";
import { useI18n } from "../i18n/I18nProvider";
import { MAX_AUTO_ATTEMPTS, sync } from "../sync/engine";
import type { SyncProgress } from "../sync/engine";

/**
 * The send queue.
 *
 * Section 7 asks for sync status to be visible rather than silent -- "a simple
 * badge showing '12 pending, 3 synced' so a worker isn't left wondering if
 * their day's work was recorded". This screen is the full version of that
 * badge, and its job is reassurance as much as control.
 *
 * The "send now" button is here because Section 7 says Background Sync is not
 * dependable across Android WebViews. Whatever the automatic triggers do, a
 * worker who can see they have signal must have a way to make something happen
 * and watch it happen.
 */

function StatusBadge({ item }: { item: QueueItem }) {
  const { t } = useI18n();
  if (item.status === "synced") {
    return (
      <span className="badge badge--synced">
        <CheckIcon size={16} />
        {t("statusSynced")}
      </span>
    );
  }
  if (item.status === "failed") {
    return (
      <span className="badge badge--failed">
        <AlertIcon size={16} />
        {t("statusFailed")}
      </span>
    );
  }
  if (item.status === "syncing") {
    return (
      <span className="badge badge--info">
        <SyncIcon size={16} />
        {t("statusSyncing")}
      </span>
    );
  }
  return (
    <span className="badge badge--pending">
      <ClockIcon size={16} />
      {t("statusPending")}
    </span>
  );
}

export function Queue() {
  const { t } = useI18n();
  const online = useOnline();
  const announce = useAnnounce();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    void listQueue().then(setItems);
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const runSync = async () => {
    setBusy(true);
    setProgress(null);
    try {
      // `force` skips backoff. A worker looking at signal bars should not be
      // told to wait for a timer they cannot see.
      const outcome = await sync({ force: true, onProgress: setProgress });
      announce(outcome.failed === 0 ? t("syncDone") : t("statusFailed"));
    } finally {
      setBusy(false);
      setProgress(null);
      refresh();
    }
  };

  const retryOne = async (id: string) => {
    // Resetting attempts is what makes a manual retry meaningful for an item
    // that has already exhausted its automatic ones.
    await updateItem(id, { status: "pending", attempts: 0, lastError: undefined });
    refresh();
    void runSync();
  };

  const confirmDelete = async (id: string) => {
    await removeItem(id);
    setConfirmId(null);
    refresh();
  };

  const pending = items.filter((i) => i.status !== "synced");

  return (
    <main className="app__main" id="main">
      <h2 className="section-title">{t("queueTitle")}</h2>

      {!online && (
        <div className="banner banner--offline" role="status">
          <OfflineIcon size={20} />
          <div className="banner__body">
            <strong className="banner__title">{t("offlineBanner")}</strong>
            <div>{t("offlineDetail")}</div>
          </div>
        </div>
      )}

      <button
        type="button"
        className="btn btn--primary btn--block btn--capture"
        onClick={runSync}
        disabled={busy || pending.length === 0}
      >
        {busy ? <span className="spinner" /> : <SyncIcon />}
        {busy ? t("syncing") : t("syncNow")}
      </button>

      {progress && progress.total > 0 && (
        <p className="text-center text-secondary" style={{ marginTop: "var(--space-3)" }} role="status">
          <span className="numeric">
            {progress.done} / {progress.total}
          </span>
          {progress.current ? ` — ${progress.current}` : ""}
        </p>
      )}

      <div style={{ marginTop: "var(--space-5)" }}>
        {items.length === 0 ? (
          <p className="empty">{t("queueEmpty")}</p>
        ) : (
          items.map((item) => (
            <div className="card" key={item.id}>
              <div className="row row--between" style={{ marginBottom: "var(--space-2)" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="card__title">{item.beneficiaryName}</div>
                  <div className="card__meta">
                    {item.kind === "capture"
                      ? `${t("captureTitle")} · ${formatBytes(item.photoBytes)}`
                      : `${t("growthTitle")} · ${item.heightCm}cm / ${item.weightKg}kg`}
                  </div>
                </div>
                <StatusBadge item={item} />
              </div>

              {item.status === "failed" && (
                <>
                  <p className="field__error" style={{ marginTop: 0 }}>
                    <AlertIcon size={16} />
                    <span>{item.lastError ?? t("errorGeneric")}</span>
                  </p>
                  <p className="card__meta">
                    {t("attemptsLabel")}: <span className="numeric">{item.attempts}</span>
                    {item.attempts >= MAX_AUTO_ATTEMPTS ? " / " + MAX_AUTO_ATTEMPTS : ""}
                  </p>
                  <div className="row" style={{ marginTop: "var(--space-3)" }}>
                    <button
                      type="button"
                      className="btn btn--secondary"
                      onClick={() => retryOne(item.id)}
                      disabled={busy}
                    >
                      <SyncIcon size={18} />
                      {t("retryItem")}
                    </button>
                    {/* Deleting queued evidence is destructive and irreversible,
                        so it is confirmed and visually separated from retry. */}
                    <button
                      type="button"
                      className="btn btn--danger"
                      onClick={() => setConfirmId(item.id)}
                    >
                      <TrashIcon size={18} />
                      {t("deleteItem")}
                    </button>
                  </div>
                </>
              )}

              {confirmId === item.id && (
                <div className="banner banner--error" role="alertdialog" aria-label={t("deleteConfirm")}>
                  <AlertIcon size={20} />
                  <div className="banner__body">
                    <div>{t("deleteConfirm")}</div>
                    <div className="row" style={{ marginTop: "var(--space-3)" }}>
                      <button
                        type="button"
                        className="btn btn--danger"
                        onClick={() => confirmDelete(item.id)}
                      >
                        {t("confirm")}
                      </button>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={() => setConfirmId(null)}
                      >
                        {t("cancel")}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </main>
  );
}
