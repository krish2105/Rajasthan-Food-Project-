import { useCallback, useEffect, useState } from "react";
import * as api from "./api/client";
import { useI18n } from "./i18n/I18nProvider";
import { useOnline, useQueueCounts } from "./components/hooks";
import {
  CameraIcon,
  CheckIcon,
  ClockIcon,
  HomeIcon,
  OfflineIcon,
  ScaleIcon,
  SettingsIcon,
  SyncIcon,
} from "./components/Icon";
import { Capture } from "./screens/Capture";
import { Growth } from "./screens/Growth";
import { Home } from "./screens/Home";
import { Queue } from "./screens/Queue";
import { Settings } from "./screens/Settings";
import { SignIn } from "./screens/SignIn";
import { cacheAwcs, cacheBeneficiaries } from "./db/queue";
import { requestPersistence } from "./db/storage";
import { startAutoSync } from "./sync/engine";

export type Screen = "home" | "capture" | "growth" | "queue" | "settings";

/**
 * App shell.
 *
 * Screen state rather than a router. Five screens, no deep links, no back-stack
 * to preserve -- a router would be several kilobytes and an API surface for
 * navigation that is genuinely this simple. If Phase 4 or 5 needs URLs, that is
 * a different app.
 *
 * The persistent pieces are the offline banner and the sync badge, both of
 * which Section 7 asks to be visible rather than silent.
 */
export function App() {
  const { t } = useI18n();
  const online = useOnline();
  const { counts, refresh } = useQueueCounts();

  const [signedIn, setSignedIn] = useState(() => api.getToken() !== null);
  const [screen, setScreen] = useState<Screen>("home");
  const [toast, setToast] = useState<string | null>(null);

  /** First sync after sign-in: caches everything needed to work offline. */
  const primeCache = useCallback(async () => {
    try {
      const [children, awcs] = await Promise.all([
        api.fetchBeneficiaries(),
        api.fetchAwcs(),
      ]);
      await cacheBeneficiaries(
        children.map((c) => ({
          id: c.id,
          name: c.name,
          awcCode: c.awc_code,
          dob: c.dob,
          gender: c.gender,
          ageMonths: c.age_months ?? 0,
          poshanTrackerId: c.poshan_tracker_id,
        })),
      );
      await cacheAwcs(
        awcs.map((a) => ({
          awcCode: a.awc_code,
          nameEn: a.name_en,
          nameHi: a.name_hi,
          district: a.district,
          districtHi: a.district_hi,
          block: a.block,
          blockHi: a.block_hi,
          centreType: a.centre_type,
        })),
      );
    } catch {
      // A failed prime is survivable: a previously cached list is still there,
      // and Settings offers a manual refresh.
    }
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    void requestPersistence();
    void primeCache();
  }, [signedIn, primeCache]);

  useEffect(() => {
    if (!signedIn) return;
    return startAutoSync((outcome) => {
      refresh();
      if (outcome.authFailure) {
        // The token expired. Sending the worker back to sign-in is the only
        // honest response; silently failing forever would look like a network
        // problem they cannot fix.
        api.clearSession();
        setSignedIn(false);
        return;
      }
      if (outcome.sent > 0) setToast(t("syncDone"));
    });
  }, [signedIn, refresh, t]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  if (!signedIn) {
    return (
      <div className="app">
        <SignIn onSignedIn={() => setSignedIn(true)} />
      </div>
    );
  }

  const waiting = counts.pending + counts.failed + counts.syncing;

  const navItems: Array<{ id: Screen; label: string; icon: React.ReactNode }> = [
    { id: "home", label: t("navHome"), icon: <HomeIcon size={22} /> },
    { id: "capture", label: t("navCapture"), icon: <CameraIcon size={22} /> },
    { id: "growth", label: t("navGrowth"), icon: <ScaleIcon size={22} /> },
    { id: "queue", label: t("navQueue"), icon: <SyncIcon size={22} /> },
  ];

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        {t("skipToContent")}
      </a>

      {/* Polite, not assertive: confirmations should be spoken without
          interrupting whatever the worker is doing. */}
      <div id="live-region" aria-live="polite" aria-atomic="true" className="sr-only" />

      <header className="header">
        <h1 className="header__title">
          {t("appName")}
          <span className="header__subtitle">{t("appTagline")}</span>
        </h1>

        {/* Section 7's visible sync status. Icon plus number plus an
            accessible label -- never a bare coloured dot. */}
        <span
          className={`badge ${online ? (waiting > 0 ? "badge--pending" : "badge--synced") : "badge--failed"}`}
          aria-label={
            online ? `${waiting} ${t("statusPending")}` : t("offlineBanner")
          }
        >
          {!online ? (
            <OfflineIcon size={16} />
          ) : waiting > 0 ? (
            <ClockIcon size={16} />
          ) : (
            <CheckIcon size={16} />
          )}
          <span className="numeric">{online ? waiting : ""}</span>
        </span>

        <button
          type="button"
          className="nav__item"
          style={{ minWidth: "var(--touch-min)" }}
          onClick={() => setScreen("settings")}
          aria-label={t("settingsTitle")}
          aria-current={screen === "settings" ? "page" : undefined}
        >
          <SettingsIcon size={22} />
        </button>
      </header>

      {!online && (
        <div
          className="banner banner--offline"
          role="status"
          style={{ margin: "var(--space-3) var(--space-4) 0", marginBottom: 0 }}
        >
          <OfflineIcon size={20} />
          <div className="banner__body">
            <strong className="banner__title">{t("offlineBanner")}</strong>
            <div>{t("offlineDetail")}</div>
          </div>
        </div>
      )}

      {screen === "home" && <Home onNavigate={setScreen} />}
      {screen === "capture" && <Capture />}
      {screen === "growth" && <Growth />}
      {screen === "queue" && <Queue />}
      {screen === "settings" && <Settings onSignedOut={() => setSignedIn(false)} />}

      {toast && (
        <div
          role="status"
          className="banner banner--success"
          style={{
            position: "fixed",
            left: "var(--space-4)",
            right: "var(--space-4)",
            bottom: `calc(var(--touch-comfortable) + var(--space-5) + env(safe-area-inset-bottom))`,
            zIndex: "var(--z-toast)",
          }}
        >
          <CheckIcon size={20} />
          <span className="banner__body">{toast}</span>
        </div>
      )}

      <nav className="nav" aria-label={t("appName")}>
        {navItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className="nav__item"
            aria-current={screen === item.id ? "page" : undefined}
            onClick={() => setScreen(item.id)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
