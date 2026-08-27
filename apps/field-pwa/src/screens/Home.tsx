import { useEffect, useState } from "react";
import * as api from "../api/client";
import { listBeneficiaries, listQueue } from "../db/queue";
import type { CachedBeneficiary } from "../db/schema";
import { useI18n } from "../i18n/I18nProvider";
import { CameraIcon, ScaleIcon } from "../components/Icon";
import type { Screen } from "../App";

/**
 * The worker's day at a glance.
 *
 * Four numbers and one list. Not a dashboard in the Phase 4 sense -- this
 * answers only what a worker needs before they start: how much have I done, how
 * much is waiting to send, and whose weight is still outstanding this month.
 *
 * Everything is computed from the local cache and the local queue, so it is
 * correct with no signal. A screen that showed "—" until the network returned
 * would be useless in exactly the conditions it is meant for.
 */
export function Home({ onNavigate }: { onNavigate: (screen: Screen) => void }) {
  const { t, lang } = useI18n();
  const worker = api.getWorker();
  const [children, setChildren] = useState<CachedBeneficiary[]>([]);
  const [capturedToday, setCapturedToday] = useState(0);
  const [pending, setPending] = useState(0);
  const [measuredThisMonth, setMeasuredThisMonth] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [kids, queue] = await Promise.all([listBeneficiaries(), listQueue()]);
      if (cancelled) return;

      const today = new Date().toISOString().slice(0, 10);
      const month = today.slice(0, 7);

      setChildren(kids);
      setCapturedToday(
        queue.filter((i) => i.kind === "capture" && i.createdAt.slice(0, 10) === today).length,
      );
      setPending(queue.filter((i) => i.status !== "synced").length);

      // Counts both what the server told us and what is still queued locally,
      // so a worker who measured ten children offline sees ten, not zero.
      const queuedThisMonth = new Set(
        queue
          .filter((i) => i.kind === "growth" && i.createdAt.slice(0, 7) === month)
          .map((i) => i.beneficiaryId),
      );
      setMeasuredThisMonth(
        kids.filter(
          (c) =>
            queuedThisMonth.has(c.id) || (c.lastMeasuredAt ?? "").slice(0, 7) === month,
        ).length,
      );
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const month = new Date().toISOString().slice(0, 7);
  const notMeasured = children.filter((c) => (c.lastMeasuredAt ?? "").slice(0, 7) !== month);

  return (
    <main className="app__main" id="main">
      <h2 className="section-title">
        {t("greeting")}
        {worker?.name ? `, ${worker.name}` : ""}
      </h2>

      <div className="stat-grid">
        <div className="stat">
          <span className="stat__value">{capturedToday}</span>
          <span className="stat__label">{t("statCaptured")}</span>
        </div>
        <div className="stat">
          <span className="stat__value">{pending}</span>
          <span className="stat__label">{t("statPending")}</span>
        </div>
        <div className="stat">
          <span className="stat__value">{measuredThisMonth}</span>
          <span className="stat__label">{t("statMeasured")}</span>
        </div>
        <div className="stat">
          <span className="stat__value">{children.length}</span>
          <span className="stat__label">{t("statChildren")}</span>
        </div>
      </div>

      {/* The two things a worker actually came here to do, as targets far
          larger than the navigation bar's. */}
      <div className="stack">
        <button
          type="button"
          className="btn btn--primary btn--block btn--capture"
          onClick={() => onNavigate("capture")}
        >
          <CameraIcon />
          {t("takePhoto")}
        </button>
        <button
          type="button"
          className="btn btn--secondary btn--block btn--capture"
          onClick={() => onNavigate("growth")}
        >
          <ScaleIcon />
          {t("saveGrowth")}
        </button>
      </div>

      <section style={{ marginTop: "var(--space-6)" }}>
        <h3 className="section-title">{t("notMeasuredTitle")}</h3>
        {notMeasured.length === 0 ? (
          <p className="empty">{t("notMeasuredEmpty")}</p>
        ) : (
          <>
            {notMeasured.slice(0, 5).map((child) => (
              <div className="card" key={child.id}>
                <div className="row row--between">
                  <div>
                    <div className="card__title">{child.name}</div>
                    <div className="card__meta">
                      {Math.floor(child.ageMonths / 12)} {t("years")}{" "}
                      {child.ageMonths % 12} {t("months")}
                    </div>
                  </div>
                  <ScaleIcon size={20} />
                </div>
              </div>
            ))}
            {notMeasured.length > 5 && (
              <p className="text-secondary text-center" style={{ marginTop: "var(--space-3)" }}>
                {lang === "hi"
                  ? `${t("andMore")} ${notMeasured.length - 5} ${t("more")}`
                  : `and ${notMeasured.length - 5} more children`}
              </p>
            )}
          </>
        )}
      </section>
    </main>
  );
}
